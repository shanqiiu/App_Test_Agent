"""
Configuration loader for model and generation settings.
"""

import yaml
from dataclasses import dataclass
from typing import List, Dict, Any
from pathlib import Path


@dataclass
class ModelConfig:
    """Model configuration."""
    name: str
    cache_dir: str


@dataclass
class GenerationConfig:
    """Generation parameters."""
    num_inference_steps: int
    guidance_scale: float
    height: int
    width: int
    negative_prompt: str


@dataclass
class GPUConfig:
    """GPU optimization settings."""
    enable_xformers: bool
    use_fp16: bool
    memory_threshold_gb: float


@dataclass
class OutputConfig:
    """Output configuration."""
    image_dir: str
    metadata_dir: str
    log_dir: str
    image_format: str


@dataclass
class Config:
    """Complete configuration."""
    model: ModelConfig
    generation: GenerationConfig
    gpu: GPUConfig
    output: OutputConfig


class ConfigLoader:
    """Load and parse YAML configuration files."""

    @staticmethod
    def load(config_path: str = None) -> Config:
        """
        Load configuration from YAML file.

        Args:
            config_path: Path to config file. If None, uses default location.

        Returns:
            Config object
        """
        if config_path is None:
            # Default to config/model_config.yaml relative to project root
            project_root = Path(__file__).parent.parent
            config_path = project_root / "config" / "model_config.yaml"

        with open(config_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        # Parse configuration sections
        model = ModelConfig(**data['model'])
        generation = GenerationConfig(**data['generation'])
        gpu = GPUConfig(**data['gpu'])
        output = OutputConfig(**data['output'])

        return Config(
            model=model,
            generation=generation,
            gpu=gpu,
            output=output
        )

    @staticmethod
    def load_prompts(prompts_path: str = None) -> List[Dict[str, str]]:
        """
        Load test prompts from JSON file.

        Args:
            prompts_path: Path to prompts file. If None, uses default location.

        Returns:
            List of prompt dictionaries
        """
        if prompts_path is None:
            project_root = Path(__file__).parent.parent
            prompts_path = project_root / "config" / "test_prompts.json"

        import json
        with open(prompts_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        return data.get('prompts', [])
