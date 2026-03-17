"""
Mock 提供器

在内网环境下不依赖生成模型 API，使用预置结果完成异常注入流水线。

用法：
    1. 准备 mock 配置文件（JSON），指定每步的决策结果
    2. 在 injection_pipeline.py 中使用 --mock 参数启用

mock 配置文件格式：
{
    "decisions": [
        {
            "step": 0,
            "decision": "SKIP",
            "think": "首页界面，操作序列刚开始",
            "conclusion": "跳过首页"
        },
        {
            "step": 2,
            "decision": "INJECT",
            "anomaly_type": "弹窗覆盖原UI",
            "instruction": "生成优惠券广告弹窗",
            "think": "用户进入搜索结果页，适合弹出广告",
            "conclusion": "在搜索结果页注入弹窗"
        }
    ],
    "fallback_inject_step": 2,
    "fallback_anomaly_type": "弹窗覆盖原UI",
    "fallback_instruction": "生成异常弹窗",
    "anomaly_images_dir": null
}
"""

import json
import shutil
from pathlib import Path
from typing import List, Dict, Optional

from .anomaly_recommender import AnomalyRecommender


class MockConfig:
    """Mock 配置加载器"""

    def __init__(self, config_path: Optional[str] = None):
        """
        Args:
            config_path: mock 配置文件路径，为 None 则使用内置默认配置
        """
        if config_path and Path(config_path).exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                self._config = json.load(f)
        else:
            self._config = self._default_config()

        # 按 step 索引建立决策映射
        self._decisions_map: Dict[int, Dict] = {}
        for d in self._config.get("decisions", []):
            self._decisions_map[d["step"]] = d

    @staticmethod
    def _default_config() -> dict:
        """内置默认配置：在第 2 步注入弹窗类异常"""
        return {
            "decisions": [
                {
                    "step": 0,
                    "decision": "SKIP",
                    "think": "[Mock] 序列起始，积累上下文",
                    "conclusion": "跳过起始步骤"
                },
                {
                    "step": 1,
                    "decision": "SKIP",
                    "think": "[Mock] 继续积累上下文",
                    "conclusion": "跳过第二步"
                },
                {
                    "step": 2,
                    "decision": "INJECT",
                    "anomaly_type": "弹窗覆盖原UI",
                    "instruction": "生成优惠券广告弹窗",
                    "think": "[Mock] 已有足够上下文，在此注入弹窗异常",
                    "conclusion": "在第 2 步注入弹窗覆盖异常"
                }
            ],
            "fallback_inject_step": 2,
            "fallback_anomaly_type": "弹窗覆盖原UI",
            "fallback_instruction": "生成异常弹窗",
            "anomaly_images_dir": None
        }

    def get_decision(self, step_index: int) -> Dict:
        """获取指定步骤的决策"""
        if step_index in self._decisions_map:
            d = self._decisions_map[step_index]
            return {
                "decision": d.get("decision", "SKIP"),
                "anomaly_type": d.get("anomaly_type"),
                "instruction": d.get("instruction"),
                "think": d.get("think", f"[Mock] Step {step_index}"),
                "conclusion": d.get("conclusion", "")
            }

        # 没有显式配置时，使用 fallback 逻辑
        fallback_step = self._config.get("fallback_inject_step", 2)
        if step_index >= fallback_step:
            return {
                "decision": "INJECT",
                "anomaly_type": self._config.get("fallback_anomaly_type", "弹窗覆盖原UI"),
                "instruction": self._config.get("fallback_instruction", "生成异常弹窗"),
                "think": f"[Mock] Step {step_index} 达到 fallback 注入步骤",
                "conclusion": f"在 Step {step_index} 执行 fallback 注入"
            }
        else:
            return {
                "decision": "SKIP",
                "anomaly_type": None,
                "instruction": None,
                "think": f"[Mock] Step {step_index} 未达到注入条件",
                "conclusion": f"跳过 Step {step_index}"
            }

    @property
    def anomaly_images_dir(self) -> Optional[Path]:
        """预置异常图片目录"""
        d = self._config.get("anomaly_images_dir")
        return Path(d) if d else None


class MockSequenceAnalyzer:
    """
    Mock 语义分析器

    替代 SequenceAnalyzer，不调用 VLM API，
    直接返回 MockConfig 中的预置决策结果。
    """

    def __init__(
        self,
        recommender: AnomalyRecommender,
        task_description: str,
        mock_config: MockConfig = None,
        min_steps_before_inject: int = 2,
        **kwargs  # 忽略 api_key/api_url/model 等参数
    ):
        self.recommender = recommender
        self.task_description = task_description
        self.mock_config = mock_config or MockConfig()
        self.min_steps_before_inject = min_steps_before_inject
        self._history: List[Dict] = []

    def analyze_step(self, screenshot_path: Path, step_index: int, total_steps: int) -> Dict:
        """返回预置的分析结果"""
        result = self.mock_config.get_decision(step_index)

        # 强制规则：前 N 步不允许注入
        if step_index < self.min_steps_before_inject and result["decision"] == "INJECT":
            print(f"  ⚠ [Mock] Step {step_index}: 前 {self.min_steps_before_inject} 步强制 SKIP")
            result["decision"] = "SKIP"
            result["anomaly_type"] = None
            result["instruction"] = None

        # 记录历史
        self._history.append({
            "step_index": step_index,
            "screenshot_path": str(screenshot_path),
            **result
        })

        return result

    def run(self, screenshots: List[Path]) -> Dict:
        """增量式分析整个截图序列（Mock 版本）"""
        screenshots = [Path(p) for p in screenshots]
        total_steps = len(screenshots)

        print(f"\n{'='*60}")
        print(f"[Mock 模式] 开始增量式序列分析")
        print(f"任务: {self.task_description}")
        print(f"序列长度: {total_steps} 步")
        print(f"{'='*60}\n")

        for i, screenshot in enumerate(screenshots):
            print(f"\n--- [Mock] Step {i}/{total_steps-1}: {screenshot.name} ---")

            result = self.analyze_step(screenshot, i, total_steps)

            print(f"  Think: {result['think']}")
            print(f"  Decision: {result['decision']}")
            if result["decision"] == "INJECT":
                print(f"  Anomaly: {result['anomaly_type']}")
                print(f"  Instruction: {result['instruction']}")

            if result["decision"] == "INJECT":
                print(f"\n{'='*60}")
                print(f"✓ [Mock] 找到注入点: Step {i}")
                print(f"  异常类型: {result['anomaly_type']}")
                print(f"  生成指令: {result['instruction']}")
                print(f"{'='*60}\n")

                return {
                    "success": True,
                    "injection_point": i,
                    "anomaly_type": result["anomaly_type"],
                    "instruction": result["instruction"],
                    "reasoning": result["think"],
                    "history": self._history
                }

        print(f"\n{'='*60}")
        print(f"⚠ [Mock] 未找到合适的注入点")
        print(f"{'='*60}\n")

        return {
            "success": False,
            "injection_point": None,
            "anomaly_type": None,
            "instruction": None,
            "reasoning": "[Mock] 遍历完整个序列，未找到预置的注入点",
            "history": self._history
        }

    def reset(self) -> None:
        self._history.clear()

    def get_history(self) -> List[Dict]:
        return list(self._history)


class MockSequenceRewriter:
    """
    Mock 序列改写器

    替代 SequenceRewriter，不调用 run_pipeline.py 生成异常截图，
    而是使用预置的异常图片或基准截图占位。
    """

    def __init__(
        self,
        output_dir: Path,
        gt_template_dir: Path = None,
        mock_config: MockConfig = None,
        **kwargs
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.mock_config = mock_config or MockConfig()

        # GT 模板目录（用于查找预置异常图片）
        if gt_template_dir is None:
            project_root = Path(__file__).parent.parent.parent
            gt_template_dir = project_root / "data" / "Agent执行遇到的典型异常UI类型" / "analysis" / "gt_templates"
        self.gt_template_dir = Path(gt_template_dir)

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
        执行序列改写（Mock 版本）

        不调用 run_pipeline.py，而是：
        1. 优先使用 mock_config.anomaly_images_dir 中的预置图片
        2. 其次使用 GT 模板中的样本图片
        3. 最后使用基准截图作为占位
        """
        original_screenshots = [Path(p) for p in original_screenshots]

        if injection_point < 0 or injection_point >= len(original_screenshots):
            raise ValueError(f"无效的注入点: {injection_point}, 序列长度: {len(original_screenshots)}")

        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_output_dir = self.output_dir / f"injection_{timestamp}"
        run_output_dir.mkdir(parents=True, exist_ok=True)

        sequence_dir = run_output_dir / "modified_sequence"
        sequence_dir.mkdir(parents=True, exist_ok=True)

        anomaly_dir = run_output_dir / "anomaly_generated"
        anomaly_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n{'='*60}")
        print(f"[Mock 模式] 开始序列改写")
        print(f"注入点: Step {injection_point}")
        print(f"异常类型: {anomaly_type}")
        print(f"输出目录: {run_output_dir}")
        print(f"{'='*60}\n")

        # Step 1: 复制注入点之前的截图
        modified_sequence = []
        for i in range(injection_point + 1):
            src = original_screenshots[i]
            dst = sequence_dir / f"step_{i:02d}{src.suffix}"
            shutil.copy2(src, dst)
            modified_sequence.append(dst)
            print(f"  复制: {src.name} → {dst.name}")

        # Step 2: 获取异常图片（Mock 版本，不调用生成模型）
        base_screenshot = original_screenshots[injection_point]
        anomaly_images = self._get_mock_anomaly_images(
            base_screenshot=base_screenshot,
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
            "mock_mode": True,
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

        if decision_log:
            log_path = run_output_dir / "decision_log.json"
            with open(log_path, 'w', encoding='utf-8') as f:
                json.dump(decision_log, f, ensure_ascii=False, indent=2)

        print(f"\n{'='*60}")
        print(f"✓ [Mock] 序列改写完成")
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

    def _get_mock_anomaly_images(
        self,
        base_screenshot: Path,
        anomaly_type: str,
        gt_sample: Optional[str],
        output_dir: Path
    ) -> List[Path]:
        """
        获取 mock 异常图片

        优先级：
        1. mock_config.anomaly_images_dir 指定的目录
        2. GT 模板库中的样本图片
        3. 基准截图作为占位
        """
        # 优先级 1: 预置异常图片目录
        preset_dir = self.mock_config.anomaly_images_dir
        if preset_dir and preset_dir.exists():
            images = self._find_images(preset_dir)
            if images:
                result = []
                for img in images:
                    dst = output_dir / img.name
                    shutil.copy2(img, dst)
                    result.append(dst)
                print(f"  [Mock] 使用预置异常图片: {preset_dir} ({len(result)} 张)")
                return result

        # 优先级 2: GT 模板样本图片
        gt_category_dir = self.gt_template_dir / anomaly_type
        if gt_category_dir.exists():
            if gt_sample:
                sample_path = gt_category_dir / gt_sample
                if sample_path.exists():
                    dst = output_dir / f"mock_anomaly_{sample_path.name}"
                    shutil.copy2(sample_path, dst)
                    print(f"  [Mock] 使用 GT 样本: {sample_path.name}")
                    return [dst]

            # 使用第一个可用样本
            images = self._find_images(gt_category_dir)
            if images:
                dst = output_dir / f"mock_anomaly_{images[0].name}"
                shutil.copy2(images[0], dst)
                print(f"  [Mock] 使用 GT 样本: {images[0].name}")
                return [dst]

        # 优先级 3: 基准截图占位
        placeholder = output_dir / f"mock_placeholder{base_screenshot.suffix}"
        shutil.copy2(base_screenshot, placeholder)
        print(f"  [Mock] 使用基准截图占位: {base_screenshot.name}")
        return [placeholder]

    @staticmethod
    def _find_images(directory: Path) -> List[Path]:
        """查找目录下的图片文件"""
        image_extensions = {'.png', '.jpg', '.jpeg', '.webp'}
        images = [
            f for f in directory.iterdir()
            if f.is_file() and f.suffix.lower() in image_extensions
        ]
        images.sort(key=lambda x: x.name)
        return images
