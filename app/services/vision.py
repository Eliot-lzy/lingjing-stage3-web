from __future__ import annotations

import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from ultralytics import SAM, YOLO

from app.services.vlm import describe_image


YOLO_MODEL_NAME = "yolo11n.pt"
SAM_MODEL_NAME = "mobile_sam.pt"
YOLO_CONFIDENCE = 0.25
YOLO_IMAGE_SIZE = 960

MODEL_LOCK = threading.Lock()
_yolo_model: YOLO | None = None
_sam_model: SAM | None = None

COLORS = [
    (46, 111, 168),
    (224, 159, 62),
    (84, 130, 53),
    (192, 80, 77),
    (112, 48, 160),
    (64, 170, 176),
]


def get_yolo_model() -> YOLO:
    global _yolo_model
    if _yolo_model is None:
        _yolo_model = YOLO(YOLO_MODEL_NAME)
    return _yolo_model


def get_sam_model() -> SAM:
    global _sam_model
    if _sam_model is None:
        _sam_model = SAM(SAM_MODEL_NAME)
    return _sam_model


def run_traditional(
    image_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    start_time = time.perf_counter()

    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError(f"OpenCV 无法读取图片: {image_path}")

    height, width = image.shape[:2]
    scale = min(1.0, YOLO_IMAGE_SIZE / max(height, width))

    if scale < 1.0:
        image = cv2.resize(
            image,
            (round(width * scale), round(height * scale)),
            interpolation=cv2.INTER_AREA,
        )

    yolo = get_yolo_model()
    result = yolo.predict(
        source=image,
        conf=YOLO_CONFIDENCE,
        device="cpu",
        imgsz=YOLO_IMAGE_SIZE,
        verbose=False,
    )[0]

    detections: list[dict[str, Any]] = []
    bboxes: list[list[float]] = []

    for box in result.boxes:
        class_id = int(box.cls[0].item())
        class_name = str(result.names[class_id])
        confidence = float(box.conf[0].item())
        coordinates = [
            float(value)
            for value in box.xyxy[0].tolist()
        ]

        bboxes.append(coordinates)
        detections.append(
            {
                "class_id": class_id,
                "class_name": class_name,
                "confidence": round(confidence, 4),
                "bbox_xyxy": [round(value, 2) for value in coordinates],
            }
        )

    counts = Counter(
        str(item["class_name"])
        for item in detections
    )

    overlay = result.plot()
    mask_count = 0

    if bboxes:
        sam = get_sam_model()
        sam_result = sam.predict(
            source=image,
            bboxes=bboxes,
            device="cpu",
            verbose=False,
        )[0]

        if sam_result.masks is not None and sam_result.masks.data is not None:
            masks = sam_result.masks.data.cpu().numpy()
            if masks.ndim == 2:
                masks = masks[None, ...]

            mask_count = len(masks)

            for index, mask in enumerate(masks):
                if index >= len(detections):
                    break

                mask = cv2.resize(
                    mask.astype(np.float32),
                    (image.shape[1], image.shape[0]),
                    interpolation=cv2.INTER_NEAREST,
                )
                binary_mask = (mask > 0.5).astype(np.uint8) * 255
                region = binary_mask > 0
                color = COLORS[index % len(COLORS)]

                if np.any(region):
                    colored = np.full_like(overlay, color)
                    overlay[region] = cv2.addWeighted(
                        overlay[region],
                        0.58,
                        colored[region],
                        0.42,
                        0,
                    )

                contours, _ = cv2.findContours(
                    binary_mask,
                    cv2.RETR_EXTERNAL,
                    cv2.CHAIN_APPROX_SIMPLE,
                )
                cv2.drawContours(overlay, contours, -1, color, 2)

    output_dir.mkdir(parents=True, exist_ok=True)
    image_output = output_dir / "traditional.jpg"
    if not cv2.imwrite(str(image_output), overlay):
        raise RuntimeError("传统方案结果图保存失败")

    elapsed_seconds = time.perf_counter() - start_time

    return {
        "model": f"{YOLO_MODEL_NAME} + {SAM_MODEL_NAME}",
        "object_count": len(detections),
        "mask_count": mask_count,
        "counts": dict(counts),
        "detections": detections,
        "image_width_processed": image.shape[1],
        "image_height_processed": image.shape[0],
        "elapsed_seconds": round(elapsed_seconds, 3),
        "result_image": image_output.name,
    }


def run_comparison(
    image_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    start_time = time.perf_counter()
    result: dict[str, Any] = {}

    with MODEL_LOCK:
        try:
            result["traditional"] = run_traditional(image_path, output_dir)
        except Exception as error:
            result["traditional"] = {
                "error": str(error),
                "object_count": 0,
                "mask_count": 0,
                "detections": [],
            }

        try:
            result["multimodal"] = describe_image(image_path, output_dir)
        except Exception as error:
            result["multimodal"] = {
                "error": str(error),
                "summary": "视觉大模型处理失败",
                "items": [],
                "total_objects": 0,
            }

        result["elapsed_seconds"] = round(
            time.perf_counter() - start_time,
            3,
        )

    return result