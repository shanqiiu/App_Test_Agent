# OmniParser Offline Deployment

`icon_caption_florence` must be shipped as a complete local Hugging Face model directory. For Florence-2, keeping only `model.safetensors` is not enough.

Required files in `weights/icon_caption_florence`:

- `config.json`
- `generation_config.json`
- `model.safetensors`
- `configuration_florence2.py`
- `modeling_florence2.py`
- `processing_florence2.py`
- `preprocessor_config.json`
- `tokenizer.json`
- `tokenizer_config.json`
- `vocab.json`

Current code now loads this directory with `local_files_only=True`, so it does not pull from `C:\\Users\\19554\\.cache\\huggingface` or the network.

## OCR assets must also be local

This repo now binds OCR to project-local paths by default (`OMNIPARSER_ALLOW_OCR_DOWNLOAD=0`):

- EasyOCR:
  - `weights/ocr/easyocr/model/craft_mlt_25k.pth`
  - `weights/ocr/easyocr/model/english_g2.pth`
- PaddleOCR:
  - `weights/ocr/paddle/det/en_PP-OCRv3_det_infer/inference.pdmodel`
  - `weights/ocr/paddle/det/en_PP-OCRv3_det_infer/inference.pdiparams`
  - `weights/ocr/paddle/rec/en_PP-OCRv4_rec_infer/inference.pdmodel`
  - `weights/ocr/paddle/rec/en_PP-OCRv4_rec_infer/inference.pdiparams`
  - `weights/ocr/paddle/cls/ch_ppocr_mobile_v2.0_cls_infer/inference.pdmodel`
  - `weights/ocr/paddle/cls/ch_ppocr_mobile_v2.0_cls_infer/inference.pdiparams`

If these files are missing, runtime will raise `FileNotFoundError` instead of downloading.

Recommended offline environment variables before runtime:

```bash
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_DATASETS_OFFLINE=1
```

Optional (online fallback): allow OCR auto-download explicitly.

```bash
export OMNIPARSER_ALLOW_OCR_DOWNLOAD=1
```

If you package OmniParser to another machine, copy the whole `weights/icon_caption_florence` and `weights/ocr` directories.

## One-command offline readiness check

```bash
conda run -n omn python check_offline_ready.py
```

This script validates required local model files and Python modules, then prints `OFFLINE_READY=YES/NO`.
