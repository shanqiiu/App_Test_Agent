"""
Model loader with GPU optimization support.
"""

import torch
from diffusers import AutoPipelineForText2Image
from src.config_loader import Config
from src.utils import setup_logger, get_gpu_memory_gb

logger = setup_logger(__name__)


class ModelLoader:
    """Load and optimize diffusion models."""

    @staticmethod
    def load(config: Config):
        """
        Load diffusion model with automatic GPU optimization.

        Args:
            config: Configuration object

        Returns:
            Optimized DiffusionPipeline
        """
        logger.info(f"Loading model: {config.model.name}")

        # Determine dtype based on config
        torch_dtype = torch.float16 if config.gpu.use_fp16 else torch.float32

        # Load model
        pipe = AutoPipelineForText2Image.from_pretrained(
            config.model.name,
            torch_dtype=torch_dtype,
            use_safetensors=True,
            cache_dir=config.model.cache_dir if config.model.cache_dir != "./models" else None
        )

        logger.info(f"Model loaded with dtype: {torch_dtype}")

        # Apply optimizations
        pipe = ModelLoader.optimize_for_gpu(pipe, config)

        return pipe

    @staticmethod
    def optimize_for_gpu(pipe, config: Config):
        """
        Apply GPU optimizations to pipeline.

        Args:
            pipe: DiffusionPipeline to optimize
            config: Configuration object

        Returns:
            Optimized pipeline
        """
        available_mem = get_gpu_memory_gb()
        logger.info(f"Available GPU memory: {available_mem:.2f}GB")

        # 1. Enable xFormers (if available)
        if config.gpu.enable_xformers:
            try:
                pipe.enable_xformers_memory_efficient_attention()
                logger.info("✓ xFormers memory efficient attention enabled")
            except Exception as e:
                logger.warning(f"xFormers not available: {e}")

        # 2. Enable attention slicing (always beneficial)
        pipe.enable_attention_slicing(1)
        logger.info("✓ Attention slicing enabled")

        # 3. Enable VAE slicing (reduces memory for decoding)
        pipe.enable_vae_slicing()
        logger.info("✓ VAE slicing enabled")

        # 4. Device placement strategy
        if not torch.cuda.is_available():
            logger.warning("CUDA not available, using CPU (this will be slow!)")
            pipe = pipe.to("cpu")
        elif available_mem < config.gpu.memory_threshold_gb:
            # Low memory: use CPU offloading
            pipe.enable_model_cpu_offload()
            logger.info(f"✓ CPU offload enabled (VRAM < {config.gpu.memory_threshold_gb}GB)")
        else:
            # Sufficient memory: full GPU mode
            pipe = pipe.to("cuda")
            logger.info(f"✓ Full GPU mode (VRAM {available_mem:.2f}GB)")

        return pipe
