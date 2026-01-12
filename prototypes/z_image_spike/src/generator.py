"""
Image generation with batch processing and metadata management.
"""

import torch
from PIL import Image
from dataclasses import dataclass
from typing import List, Dict, Optional
from pathlib import Path
import time

from src.config_loader import Config
from src.utils import setup_logger, ensure_dir, save_json, clear_gpu_cache

logger = setup_logger(__name__)


@dataclass
class GenerationResult:
    """Result of image generation."""
    prompt_id: str
    image_path: Optional[str] = None
    metadata_path: Optional[str] = None
    success: bool = False
    error_msg: Optional[str] = None
    generation_time: float = 0.0


class ImageGenerator:
    """Text-to-image generator with batch processing."""

    def __init__(self, pipeline, config: Config):
        """
        Initialize generator.

        Args:
            pipeline: Loaded DiffusionPipeline
            config: Configuration object
        """
        self.pipeline = pipeline
        self.config = config
        self.default_seed = 42

    def generate(
        self,
        prompt: str,
        negative_prompt: str = "",
        seed: Optional[int] = None
    ) -> Image.Image:
        """
        Generate single image from text prompt.

        Args:
            prompt: Text description
            negative_prompt: Negative prompt (optional)
            seed: Random seed for reproducibility

        Returns:
            Generated PIL Image
        """
        # Use configured negative prompt if not specified
        if not negative_prompt:
            negative_prompt = self.config.generation.negative_prompt

        # Set seed
        seed = seed if seed is not None else self.default_seed
        if torch.cuda.is_available():
            generator = torch.Generator(device="cuda").manual_seed(seed)
        else:
            generator = torch.Generator(device="cpu").manual_seed(seed)

        # Generate image
        try:
            image = self.pipeline(
                prompt=prompt,
                negative_prompt=negative_prompt,
                num_inference_steps=self.config.generation.num_inference_steps,
                guidance_scale=self.config.generation.guidance_scale,
                height=self.config.generation.height,
                width=self.config.generation.width,
                generator=generator
            ).images[0]

            return image

        except torch.cuda.OutOfMemoryError:
            logger.error("GPU OOM detected, clearing cache")
            clear_gpu_cache()
            raise

    def generate_batch(self, prompts: List[Dict]) -> List[GenerationResult]:
        """
        Generate images for multiple prompts.

        Args:
            prompts: List of prompt dictionaries with keys: id, prompt, category, app

        Returns:
            List of GenerationResult objects
        """
        results = []
        total = len(prompts)

        logger.info(f"Starting batch generation for {total} prompts")

        for idx, item in enumerate(prompts, 1):
            prompt_id = item["id"]
            prompt = item["prompt"]
            category = item.get("category", "unknown")

            logger.info(f"[{idx}/{total}] Processing {prompt_id} ({category})")
            logger.info(f"  Prompt: {prompt[:80]}...")

            try:
                # Generate image
                start_time = time.time()
                image = self.generate(prompt, seed=self.default_seed)
                generation_time = time.time() - start_time

                # Save image
                image_path = self.save_image(image, prompt_id)

                # Save metadata
                metadata = {
                    "id": prompt_id,
                    "prompt": prompt,
                    "category": category,
                    "app": item.get("app", "unknown"),
                    "seed": self.default_seed,
                    "generation_time": round(generation_time, 2),
                    "parameters": {
                        "num_inference_steps": self.config.generation.num_inference_steps,
                        "guidance_scale": self.config.generation.guidance_scale,
                        "height": self.config.generation.height,
                        "width": self.config.generation.width
                    }
                }
                metadata_path = self.save_metadata(metadata, prompt_id)

                results.append(GenerationResult(
                    prompt_id=prompt_id,
                    image_path=image_path,
                    metadata_path=metadata_path,
                    success=True,
                    generation_time=generation_time
                ))

                logger.info(f"  ✓ Generated in {generation_time:.2f}s: {image_path}")

            except Exception as e:
                logger.error(f"  ✗ Failed: {e}")
                results.append(GenerationResult(
                    prompt_id=prompt_id,
                    success=False,
                    error_msg=str(e)
                ))

        success_count = sum(1 for r in results if r.success)
        logger.info(f"Batch generation completed: {success_count}/{total} succeeded")

        return results

    def save_image(self, image: Image.Image, prompt_id: str) -> str:
        """
        Save generated image.

        Args:
            image: PIL Image
            prompt_id: Unique identifier

        Returns:
            Path to saved image
        """
        output_dir = ensure_dir(self.config.output.image_dir)
        image_path = output_dir / f"{prompt_id}.{self.config.output.image_format}"
        image.save(image_path)
        return str(image_path)

    def save_metadata(self, metadata: Dict, prompt_id: str) -> str:
        """
        Save generation metadata.

        Args:
            metadata: Metadata dictionary
            prompt_id: Unique identifier

        Returns:
            Path to saved metadata file
        """
        output_dir = ensure_dir(self.config.output.metadata_dir)
        metadata_path = output_dir / f"{prompt_id}.json"
        save_json(metadata, str(metadata_path))
        return str(metadata_path)
