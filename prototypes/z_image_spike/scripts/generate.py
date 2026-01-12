"""
Text-to-image generation CLI.

Usage:
  python scripts/generate.py                    # Generate all test scenarios
  python scripts/generate.py --prompt "..."    # Generate single image
  python scripts/generate.py --seed 42         # Specify random seed
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config_loader import ConfigLoader
from src.model_loader import ModelLoader
from src.generator import ImageGenerator
from src.utils import setup_logger


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Generate anomaly UI screenshots using SDXL Turbo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate all test scenarios
  python scripts/generate.py

  # Generate single image with custom prompt
  python scripts/generate.py --prompt "A payment app with error message"

  # Specify seed for reproducibility
  python scripts/generate.py --seed 123
        """
    )
    parser.add_argument(
        "--prompt",
        type=str,
        help="Custom prompt for single generation"
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed (default: 42)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output directory (overrides config)"
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to config file (default: config/model_config.yaml)"
    )

    args = parser.parse_args()

    # Setup logger
    log_file = project_root / "outputs" / "logs" / "generate.log"
    logger = setup_logger("generate", log_file=str(log_file))

    logger.info("="*60)
    logger.info("Z-Image Spike - Text-to-Image Generation")
    logger.info("="*60)

    try:
        # Load configuration
        logger.info("Loading configuration...")
        config = ConfigLoader.load(args.config)
        logger.info(f"  Model: {config.model.name}")
        logger.info(f"  Steps: {config.generation.num_inference_steps}")
        logger.info(f"  Size: {config.generation.height}x{config.generation.width}")

        # Override output directory if specified
        if args.output:
            config.output.image_dir = args.output

        # Load model
        logger.info("\nLoading model (this may take a few minutes on first run)...")
        pipeline = ModelLoader.load(config)
        logger.info("Model loaded successfully!")

        # Create generator
        generator = ImageGenerator(pipeline, config)
        generator.default_seed = args.seed

        # Generate images
        if args.prompt:
            # Single image generation
            logger.info(f"\nGenerating single image with seed {args.seed}")
            logger.info(f"Prompt: {args.prompt}")

            image = generator.generate(args.prompt, seed=args.seed)

            output_path = Path(config.output.image_dir) / "custom.png"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            image.save(output_path)

            logger.info(f"✓ Image saved to: {output_path}")

        else:
            # Batch generation
            logger.info("\nLoading test prompts...")
            prompts = ConfigLoader.load_prompts()
            logger.info(f"Found {len(prompts)} test scenarios")

            logger.info(f"\nStarting batch generation with seed {args.seed}...")
            logger.info("-" * 60)

            results = generator.generate_batch(prompts)

            # Print summary
            logger.info("-" * 60)
            success_count = sum(1 for r in results if r.success)
            total_time = sum(r.generation_time for r in results if r.success)

            print("\n" + "=" * 60)
            print("Generation Results")
            print("=" * 60)

            for result in results:
                if result.success:
                    status = "✅"
                    info = f"{result.image_path} ({result.generation_time:.2f}s)"
                else:
                    status = "❌"
                    info = result.error_msg

                print(f"{status} {result.prompt_id}: {info}")

            print("=" * 60)
            print(f"Summary: {success_count}/{len(results)} succeeded")
            if success_count > 0:
                avg_time = total_time / success_count
                print(f"Average generation time: {avg_time:.2f}s")
            print(f"Output directory: {config.output.image_dir}")
            print("=" * 60)

    except KeyboardInterrupt:
        logger.info("\nGeneration interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\nError: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
