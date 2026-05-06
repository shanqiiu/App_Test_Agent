"""
序列改写器

根据注入决策结果，调用已有异常生成器，并改写操作序列。
"""

import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

from app.core.config import config


class SequenceRewriter:
    """
    序列改写器

    职责：
    1. 调用已有的 run_pipeline.py 生成异常截图
    2. 将异常截图插入到操作序列的指定位置
    3. 截断后续步骤
    4. 保存元数据和决策日志
    """

    def __init__(
        self,
        output_dir: Path,
        gt_template_dir: Path = None,
        scripts_dir: Path = None
    ):
        """
        初始化序列改写器

        Args:
            output_dir: 输出目录
            gt_template_dir: GT 模板目录，默认使用项目标准路径
            scripts_dir: scripts 目录路径，默认使用集中配置
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 使用集中配置
        self.scripts_dir = Path(scripts_dir) if scripts_dir else config.SCRIPTS_DIR
        self.gt_template_dir = Path(gt_template_dir) if gt_template_dir else config.GT_TEMPLATES_DIR

        # run_pipeline.py 路径
        self.pipeline_script = self.scripts_dir / "run_pipeline.py"
        if not self.pipeline_script.exists():
            raise FileNotFoundError(f"run_pipeline.py 不存在: {self.pipeline_script}")

    # 不需要 GT 参考图的异常模式列表
    NO_GT_MODES = {
        'modify_text', 'modify_text_ai', 'modify_text_ocr', 'modify_text_e2e',
        'text_overlay', 'area_loading', 'content_duplicate',
    }

    def rewrite(
        self,
        original_screenshots: List[Path],
        injection_point: int,
        anomaly_type: str,
        instruction: str,
        gt_sample: str = None,
        gt_category: str = None,
        decision_log: Dict = None
    ) -> Dict:
        """
        执行序列改写

        Args:
            original_screenshots: 原始截图路径列表
            injection_point: 注入位置（截图索引）
            anomaly_type: 异常类型（对应 GT 模板目录名）
            instruction: 异常生成指令
            gt_sample: GT 样本名称，默认使用第一个可用样本
            gt_category: GT 类别名称（为空则根据 anomaly_type 推断）
            decision_log: 决策日志（可选）

        Returns:
            {
                "success": True/False,
                "output_path": Path,
                "modified_sequence": List[Path],
                "original_length": int,
                "modified_length": int,
                "anomaly_images": List[Path],
                "metadata": dict
            }
        """
        original_screenshots = [Path(p) for p in original_screenshots]

        # 验证输入
        if injection_point < 0 or injection_point >= len(original_screenshots):
            raise ValueError(f"无效的注入点: {injection_point}, 序列长度: {len(original_screenshots)}")

        # 规范化异常类型名称（去除空格）
        anomaly_type_normalized = anomaly_type.replace(" ", "")

        # 确定 GT 样本（仅 dialog 模式需要，其他模式不需要）
        need_gt = anomaly_type_normalized not in self.NO_GT_MODES
        if need_gt:
            if gt_sample is None:
                gt_sample = self._get_default_sample(anomaly_type_normalized)
            if gt_sample is None:
                # 如果找不到 GT 样本但确实需要，尝试使用 dialog 类别
                gt_sample = self._get_default_sample('dialog')
            if gt_sample is None and need_gt:
                raise ValueError(f"找不到异常类型 '{anomaly_type}' 的 GT 样本，"
                                f"请确保 {self.gt_template_dir / anomaly_type_normalized} 目录存在")
        else:
            gt_sample = gt_sample or ""

        # 创建输出目录
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_output_dir = self.output_dir / f"injection_{timestamp}"
        run_output_dir.mkdir(parents=True, exist_ok=True)

        sequence_dir = run_output_dir / "modified_sequence"
        sequence_dir.mkdir(parents=True, exist_ok=True)

        anomaly_dir = run_output_dir / "anomaly_generated"
        anomaly_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n{'='*60}")
        print(f"开始序列改写")
        print(f"注入点: Step {injection_point}")
        print(f"异常类型: {anomaly_type}")
        print(f"输出目录: {run_output_dir}")
        print(f"{'='*60}\n")

        # Step 1: 复制全部原始截图到序列目录
        modified_sequence = []
        for i in range(len(original_screenshots)):
            src = original_screenshots[i]
            dst = sequence_dir / f"step_{i:02d}{src.suffix}"
            shutil.copy2(src, dst)
            modified_sequence.append(dst)
            print(f"  复制: {src.name} → {dst.name}")

        # Step 2: 调用已有生成器生成异常截图
        base_screenshot = original_screenshots[injection_point]
        anomaly_images = self._call_generator(
            screenshot_path=base_screenshot,
            instruction=instruction,
            anomaly_type=anomaly_type,
            gt_sample=gt_sample,
            output_dir=anomaly_dir
        )

        # Step 3: 将异常截图插入到序列中
        # 序列逻辑（关闭弹窗后应回到同一张原图，而非跳转到下一步）：
        #   step_N              - 弹窗前的正常操作（N = injection_point）
        #   step_N+1_anomaly    - 弹窗出现（异常图，基于 N 生成）
        #   step_N+2.jpg        - 关闭弹窗 → 回到同一界面（复制 N）
        #   step_N+3.jpg        - 继续操作（原图 N+1 平移至此）
        anomaly_sequence_paths = []
        insert_start = injection_point + 1  # 插入起始位置

        # 3a. 将 injection_point 之后的所有原图号 +2，腾出两步位置
        # 从最后一张倒序到 injection_point+1（不移动注入点本身）
        for i in range(len(original_screenshots) - 1, injection_point, -1):
            src_name = f"step_{i:02d}"
            dst_name = f"step_{i + 2:02d}"
            for ext in ['.jpg', '.jpeg', '.png', '.webp']:
                src_path = sequence_dir / f"{src_name}{ext}"
                if src_path.exists():
                    dst_path = sequence_dir / f"{dst_name}{ext}"
                    src_path.rename(dst_path)
                    break

        # 3b. 插入异常图（位置: injection_point + 1）
        anomaly_img = anomaly_images[0]
        anomaly_dst = sequence_dir / f"step_{insert_start:02d}_anomaly{anomaly_img.suffix}"
        shutil.copy2(anomaly_img, anomaly_dst)
        modified_sequence.append(anomaly_dst)
        anomaly_sequence_paths.append(anomaly_dst)
        print(f"  异常: {anomaly_img.name} → {anomaly_dst.name}")

        # 3c. 插入注入点原图副本（位置: injection_point + 2，模拟关闭弹窗恢复界面）
        base_src = original_screenshots[injection_point]
        restore_dst = sequence_dir / f"step_{insert_start + 1:02d}{base_src.suffix}"
        shutil.copy2(base_src, restore_dst)
        modified_sequence.append(restore_dst)
        print(f"  恢复: {base_src.name} → {restore_dst.name}")

        # Step 4: 保存元数据
        metadata = {
            "timestamp": timestamp,
            "original_length": len(original_screenshots),
            "modified_length": len(modified_sequence),
            "injection_point": injection_point,
            "anomaly_type": anomaly_type,
            "anomaly_type_normalized": anomaly_type_normalized,
            "gt_sample": gt_sample,
            "instruction": instruction,
            "inserted_steps": len(anomaly_images),  # 插入的异常步数
            "anomaly_images_count": len(anomaly_images),
            "original_screenshots": [str(p) for p in original_screenshots],
            "modified_sequence": [str(p) for p in modified_sequence],
            "anomaly_images": [str(p) for p in anomaly_sequence_paths]
        }

        metadata_path = run_output_dir / "metadata.json"
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

        # Step 5: 保存决策日志
        if decision_log:
            log_path = run_output_dir / "decision_log.json"
            with open(log_path, 'w', encoding='utf-8') as f:
                json.dump(decision_log, f, ensure_ascii=False, indent=2)

        print(f"\n{'='*60}")
        print(f"✓ 序列改写完成")
        print(f"  原始长度: {len(original_screenshots)}")
        print(f"  改写后长度: {len(modified_sequence)}")
        print(f"  插入异常数: {len(anomaly_images)}")
        print(f"  输出目录: {run_output_dir}")
        print(f"{'='*60}\n")

        return {
            "success": True,
            "output_path": run_output_dir,
            "modified_sequence": modified_sequence,
            "original_length": len(original_screenshots),
            "modified_length": len(modified_sequence),
            "anomaly_images": anomaly_sequence_paths,
            "metadata": metadata
        }

    def _call_generator(
        self,
        screenshot_path: Path,
        instruction: str,
        anomaly_type: str,
        gt_sample: str,
        output_dir: Path
    ) -> List[Path]:
        """
        调用已有的 run_pipeline.py 生成异常截图

        Args:
            screenshot_path: 基准截图路径
            instruction: 生成指令
            anomaly_type: 异常类型
            gt_sample: GT 样本名称
            output_dir: 输出目录

        Returns:
            生成的异常截图路径列表
        """
        print(f"\n  调用异常生成器...")
        print(f"  基准截图: {screenshot_path}")
        print(f"  指令: {instruction}")

        # 确定 anomaly_mode
        anomaly_mode = self._get_anomaly_mode(anomaly_type)

        # 构建命令（仅 dialog 模式需要 gt-category 和 gt-sample）
        cmd = [
            sys.executable,
            str(self.pipeline_script),
            "--screenshot", str(screenshot_path),
            "--instruction", instruction,
            "--anomaly-mode", anomaly_mode,
            "--output", str(output_dir)
        ]
        if anomaly_mode == 'dialog' and gt_sample:
            # dialog 模式需要 GT 参考图
            cmd += ["--gt-category", anomaly_type, "--gt-sample", gt_sample]
        elif gt_sample:
            # 其他模式如果有指定 gt_sample 也传入
            cmd += ["--gt-category", anomaly_type, "--gt-sample", gt_sample]

        print(f"  命令: {' '.join(cmd)}")

        try:
            # 执行生成器，实时显示输出（UTF-8 编码处理 Windows GBK 问题）
            process = subprocess.Popen(
                cmd,
                cwd=str(self.scripts_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                # 不使用 text=True，改为手动解码以避免Windows编码问题
            )

            print(f"\n  {'='*60}")
            print(f"  [生成器输出开始]")
            print(f"  {'='*60}\n")

            # 实时打印输出（修复Windows编码问题）
            while True:
                line = process.stdout.readline()
                if not line:
                    break
                try:
                    # 尝试解码，失败则使用替换模式
                    decoded_line = line.decode('utf-8', errors='replace').rstrip()
                    print(f"  {decoded_line}")
                    sys.stdout.flush()  # 强制刷新输出
                except Exception as e:
                    print(f"  [解码错误: {e}]")
                    sys.stdout.flush()
                
                if process.poll() is not None:
                    # 进程已结束，读取剩余输出
                    remaining = process.stdout.read()
                    if remaining:
                        try:
                            print(f"  {remaining.decode('utf-8', errors='replace')}")
                        except:
                            pass
                    break

            process.wait(timeout=300)

            if process.returncode != 0:
                print(f"\n  ⚠ 生成器返回错误 (exit code: {process.returncode})")
            else:
                print(f"\n  {'='*60}")
                print(f"  [生成器输出结束]")
                print(f"  {'='*60}\n")

        except subprocess.TimeoutExpired:
            print(f"\n  ⚠ 生成器超时 (5分钟)")
            process.kill()
        except Exception as e:
            print(f"\n  ⚠ 生成器调用失败: {e}")

        # 查找生成的异常截图
        anomaly_images = self._find_generated_images(output_dir)

        if not anomaly_images:
            print(f"  ⚠ 未找到生成的异常截图，使用占位图")
            # 创建占位图（复制原图作为占位）
            placeholder = output_dir / "anomaly_placeholder.png"
            shutil.copy2(screenshot_path, placeholder)
            anomaly_images = [placeholder]

        print(f"  生成了 {len(anomaly_images)} 张异常截图")
        return anomaly_images

    def _find_generated_images(self, output_dir: Path) -> List[Path]:
        """查找最终生成的异常截图（仅 final_*.png）"""
        images = []

        for f in output_dir.iterdir():
            if f.is_file() and f.suffix.lower() == '.png':
                # 只取 final_ 开头的最终合成结果
                # 排除 dialog_only（独立弹窗）、vis_bbox（检测框可视化）、
                # annotated（标注图）、debug（调试）、stage1/2（中间结果）
                if f.name.startswith('final_'):
                    images.append(f)

        # 按文件名排序
        images.sort(key=lambda x: x.name)
        return images

    def _get_anomaly_mode(self, anomaly_type: str) -> str:
        """根据异常类型确定 anomaly_mode 参数"""
        mode_mapping = {
            "dialog": "dialog",
            "area_loading": "area_loading",
            "content_duplicate": "content_duplicate",
            "modify_text": "modify_text",
            "modify_text_ai": "modify_text_ai",
            "modify_text_ocr": "modify_text_ocr",
            "modify_text_e2e": "modify_text_e2e",
            "text_overlay": "text_overlay",
        }
        return mode_mapping.get(anomaly_type, anomaly_type)

    def _get_default_sample(self, anomaly_type: str) -> Optional[str]:
        """获取指定类型的默认样本"""
        category_dir = self.gt_template_dir / anomaly_type
        if not category_dir.exists():
            return None

        # 查找图片文件
        for ext in ['.jpg', '.jpeg', '.png']:
            samples = list(category_dir.glob(f'*{ext}'))
            if samples:
                return samples[0].name

        return None
