"""
成本追踪模块

记录API调用成本,生成成本报告
"""

import json
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
from pathlib import Path


logger = logging.getLogger("model_api_spike")


class CostTracker:
    """成本追踪器"""

    def __init__(self):
        """初始化成本追踪器"""
        self.records: List[Dict[str, Any]] = []
        self.start_time = datetime.now()

    def record(
        self,
        provider: str,
        cost: float,
        scenario_id: str,
        generation_time: float,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        记录一次API调用

        Args:
            provider: API提供商名称
            cost: 成本(美元)
            scenario_id: 场景ID
            generation_time: 生成耗时(秒)
            metadata: 其他元数据(可选)
        """
        record = {
            "timestamp": datetime.now().isoformat(),
            "provider": provider,
            "scenario_id": scenario_id,
            "cost_usd": round(cost, 4),
            "generation_time_sec": round(generation_time, 2),
            "metadata": metadata or {}
        }
        self.records.append(record)
        logger.debug(f"Cost recorded: {scenario_id} - ${cost:.4f}")

    def get_summary(self) -> Dict[str, Any]:
        """
        获取成本汇总

        Returns:
            汇总字典
        """
        if not self.records:
            return {
                "total_cost": 0.0,
                "total_images": 0,
                "avg_cost_per_image": 0.0,
                "by_provider": {},
                "by_scenario": {}
            }

        total_cost = sum(r["cost_usd"] for r in self.records)
        total_images = len(self.records)
        avg_cost = total_cost / total_images if total_images > 0 else 0.0

        # 按provider统计
        by_provider = {}
        for record in self.records:
            provider = record["provider"]
            if provider not in by_provider:
                by_provider[provider] = {
                    "count": 0,
                    "total_cost": 0.0
                }
            by_provider[provider]["count"] += 1
            by_provider[provider]["total_cost"] += record["cost_usd"]

        # 计算每个provider的平均成本
        for provider, stats in by_provider.items():
            stats["avg_cost"] = round(stats["total_cost"] / stats["count"], 4)
            stats["total_cost"] = round(stats["total_cost"], 4)

        # 按场景统计
        by_scenario = {}
        for record in self.records:
            scenario_id = record["scenario_id"]
            by_scenario[scenario_id] = {
                "cost": record["cost_usd"],
                "time_sec": record["generation_time_sec"],
                "provider": record["provider"]
            }

        return {
            "total_cost": round(total_cost, 4),
            "total_images": total_images,
            "avg_cost_per_image": round(avg_cost, 4),
            "by_provider": by_provider,
            "by_scenario": by_scenario
        }

    def get_total_cost(self) -> float:
        """获取总成本"""
        return sum(r["cost_usd"] for r in self.records)

    def get_total_time(self) -> float:
        """获取总耗时"""
        return sum(r["generation_time_sec"] for r in self.records)

    def save_report(self, output_path: str) -> None:
        """
        保存成本报告

        Args:
            output_path: 输出文件路径(JSON)
        """
        summary = self.get_summary()
        report = {
            "timestamp": datetime.now().isoformat(),
            "session_start": self.start_time.isoformat(),
            "session_duration_sec": (datetime.now() - self.start_time).total_seconds(),
            "summary": summary,
            "details": self.records
        }

        # 确保目录存在
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        logger.info(f"Cost report saved to: {output_path}")

    def print_summary(self) -> None:
        """打印成本汇总到控制台"""
        summary = self.get_summary()

        print("\n" + "=" * 60)
        print("Cost Summary".center(60))
        print("=" * 60)

        if summary["total_images"] == 0:
            print("No images generated yet.")
            return

        print(f"Total Images:        {summary['total_images']}")
        print(f"Total Cost:          ${summary['total_cost']:.4f}")
        print(f"Avg Cost per Image:  ${summary['avg_cost_per_image']:.4f}")
        print()

        # 按provider统计
        if summary["by_provider"]:
            print("By Provider:")
            for provider, stats in summary["by_provider"].items():
                print(f"  {provider}:")
                print(f"    Count: {stats['count']}")
                print(f"    Total Cost: ${stats['total_cost']:.4f}")
                print(f"    Avg Cost: ${stats['avg_cost']:.4f}")

        print("=" * 60)
