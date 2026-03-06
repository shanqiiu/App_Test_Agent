"""
序列改写器

根据注入决策结果，调用已有异常生成器，并改写操作序列。
"""

import os
import sys
import json
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

# 添加 scripts 目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))


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
            scripts_dir: scripts 目录路径，默认自动检测
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 设置路径
        if scripts_dir is None:
            scripts_dir = Path(__file__).parent.parent
        self.scripts_dir = Path(scripts_dir)

        if gt_template_dir is None:
            project_root = self.scripts_dir.parent
            gt_template_dir = project_root / "data" / "Agent执行遇到的典型异常UI类型" / "analysis" / "gt_templates"
        self.gt_template_dir = Path(gt_template_dir)

        # run_pipeline.py 路径
        self.pipeline_script = self.scripts_dir / "run_pipeline.py"
        if not self.pipeline_script.exists():
            raise FileNotFoundError(f"run_pipeline.py 不存在: {self.pipeline_script}")

    def rewrite(
        self,
        original_screenshots: List[Path],
        injection_point: int,
        anomaly_type: str,
        instruction: str,
        gt_sample: str = None,
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

        # 确定 GT 样本
        if gt_sample is None:
            gt_sample = self._get_default_sample(anomaly_type)
            if gt_sample is None:
                raise ValueError(f"找不到异常类型 '{anomaly_type}' 的 GT 样本")

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

        # Step 1: 复制注入点之前的截图（包含注入点）
        modified_sequence = []
        for i in range(injection_point + 1):
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

        # Step 3: 将异常截图添加到序列
        anomaly_sequence_paths = []
        for j, anomaly_img in enumerate(anomaly_images):
            dst = sequence_dir / f"step_{injection_point + 1 + j:02d}_anomaly{anomaly_img.suffix}"
            shutil.copy2(anomaly_img, dst)
            modified_sequence.append(dst)
            anomaly_sequence_paths.append(dst)
            print(f"  添加异常: {anomaly_img.name} → {dst.name}")

        # Step 4: 保存元数据
        metadata = {
            "timestamp": timestamp,
            "original_length": len(original_screenshots),
            "modified_length": len(modified_sequence),
            "injection_point": injection_point,
            "anomaly_type": anomaly_type,
            "gt_sample": gt_sample,
            "instruction": instruction,
            "truncated_steps": len(original_screenshots) - injection_point - 1,
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
        print(f"  截断步骤数: {metadata['truncated_steps']}")
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

        # 构建命令
        cmd = [
            sys.executable,
            str(self.pipeline_script),
            "--screenshot", str(screenshot_path),
            "--instruction", instruction,
            "--anomaly-mode", anomaly_mode,
            "--gt-category", anomaly_type,
            "--gt-sample", gt_sample,
            "--output", str(output_dir)
        ]

        print(f"  命令: {' '.join(cmd)}")

        try:
            # 执行生成器
            result = subprocess.run(
                cmd,
                cwd=str(self.scripts_dir),
                capture_output=True,
                text=True,
                timeout=300  # 5分钟超时
            )

            if result.returncode != 0:
                print(f"  ⚠ 生成器返回错误:")
                print(f"  stdout: {result.stdout[:500] if result.stdout else 'N/A'}")
                print(f"  stderr: {result.stderr[:500] if result.stderr else 'N/A'}")
                # 继续执行，尝试查找已生成的文件

        except subprocess.TimeoutExpired:
            print(f"  ⚠ 生成器超时")
        except Exception as e:
            print(f"  ⚠ 生成器调用失败: {e}")

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
        """查找生成的图片文件"""
        image_extensions = {'.png', '.jpg', '.jpeg', '.webp'}
        images = []

        for f in output_dir.iterdir():
            if f.is_file() and f.suffix.lower() in image_extensions:
                # 排除一些中间文件
                if not any(skip in f.name.lower() for skip in ['annotated', 'debug', 'mask']):
                    images.append(f)

        # 按文件名排序
        images.sort(key=lambda x: x.name)
        return images

    def _get_anomaly_mode(self, anomaly_type: str) -> str:
        """根据异常类型确定 anomaly_mode 参数"""
        mode_mapping = {
            "弹窗覆盖原UI": "dialog",
            "内容歧义、重复": "content_duplicate",
            "loading_timeout": "area_loading"
        }
        return mode_mapping.get(anomaly_type, "dialog")

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
