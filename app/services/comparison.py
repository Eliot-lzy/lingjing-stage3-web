from __future__ import annotations

import time
from pathlib import Path


def run_comparison(image_path: Path) -> dict[str, object]:
    """
    Temporary processing pipeline.

    The next development step replaces this function with YOLO, SAM and
    the vision language model.
    """
    start_time = time.perf_counter()
    time.sleep(2)

    elapsed_seconds = round(time.perf_counter() - start_time, 3)

    return {
        "mode": "placeholder",
        "image_path": str(image_path),
        "traditional": {
            "model": "YOLO + SAM",
            "object_count": 0,
            "mask_count": 0,
            "detections": [],
        },
        "multimodal": {
            "model": "GLM-4.6V-Flash",
            "summary": "模型处理接口将在下一阶段接入。",
            "items": [],
        },
        "elapsed_seconds": elapsed_seconds,
    }