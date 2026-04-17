#!/usr/bin/env python3
"""Check whether OmniParser can run in offline mode with local assets only."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent

REQUIRED_FILES = {
    "Florence2 caption model": [
        "weights/icon_caption_florence/config.json",
        "weights/icon_caption_florence/generation_config.json",
        "weights/icon_caption_florence/model.safetensors",
        "weights/icon_caption_florence/configuration_florence2.py",
        "weights/icon_caption_florence/modeling_florence2.py",
        "weights/icon_caption_florence/processing_florence2.py",
        "weights/icon_caption_florence/preprocessor_config.json",
        "weights/icon_caption_florence/tokenizer.json",
        "weights/icon_caption_florence/tokenizer_config.json",
        "weights/icon_caption_florence/vocab.json",
    ],
    "EasyOCR local assets": [
        "weights/ocr/easyocr/model/craft_mlt_25k.pth",
        "weights/ocr/easyocr/model/english_g2.pth",
    ],
    "PaddleOCR local assets": [
        "weights/ocr/paddle/det/en_PP-OCRv3_det_infer/inference.pdmodel",
        "weights/ocr/paddle/det/en_PP-OCRv3_det_infer/inference.pdiparams",
        "weights/ocr/paddle/rec/en_PP-OCRv4_rec_infer/inference.pdmodel",
        "weights/ocr/paddle/rec/en_PP-OCRv4_rec_infer/inference.pdiparams",
        "weights/ocr/paddle/cls/ch_ppocr_mobile_v2.0_cls_infer/inference.pdmodel",
        "weights/ocr/paddle/cls/ch_ppocr_mobile_v2.0_cls_infer/inference.pdiparams",
    ],
}

REQUIRED_MODULES = [
    "torch",
    "torchvision",
    "ultralytics",
    "transformers",
    "easyocr",
    "paddleocr",
    "accelerate",
    "einops",
]


def check_files() -> list[str]:
    missing: list[str] = []
    for group, relpaths in REQUIRED_FILES.items():
        print(f"[Check] {group}")
        for relpath in relpaths:
            abspath = ROOT / relpath
            if abspath.exists():
                print(f"  [OK] {relpath}")
            else:
                print(f"  [MISSING] {relpath}")
                missing.append(relpath)
    return missing


def check_modules() -> list[str]:
    missing: list[str] = []
    print("[Check] Python modules")
    for name in REQUIRED_MODULES:
        if importlib.util.find_spec(name):
            print(f"  [OK] {name}")
        else:
            print(f"  [MISSING] {name}")
            missing.append(name)
    return missing


def main() -> int:
    print(f"[Info] Project root: {ROOT}")
    print("[Info] Offline env vars (recommended):")
    for k in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE"):
        print(f"  - {k}={os.environ.get(k, '<unset>')}")

    missing_files = check_files()
    missing_modules = check_modules()

    print("\n[Result]")
    if not missing_files and not missing_modules:
        print("  OFFLINE_READY=YES")
        print("  Suggested run command:")
        print(
            "  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1 "
            "conda run -n omn python omni_inference.py --image 05.jpg --output results --device cuda"
        )
        return 0

    print("  OFFLINE_READY=NO")
    if missing_files:
        print("  Missing files:")
        for p in missing_files:
            print(f"    - {p}")
    if missing_modules:
        print("  Missing modules:")
        for m in missing_modules:
            print(f"    - {m}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
