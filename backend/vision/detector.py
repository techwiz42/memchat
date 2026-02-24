"""YOLO object detection wrapper.

Loads a YOLOv8 model (nano by default) and runs inference on JPEG frames.
All functions are synchronous — call via run_in_executor from async code.
"""

import logging
from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np
from ultralytics import YOLO

from config import settings

logger = logging.getLogger(__name__)


@dataclass
class Detection:
    class_name: str
    confidence: float
    bbox: tuple[int, int, int, int]  # x1, y1, x2, y2


@lru_cache(maxsize=1)
def _load_model() -> YOLO:
    """Load and cache the YOLO model singleton."""
    model_name = settings.yolo_model
    logger.info("Loading YOLO model: %s", model_name)
    model = YOLO(model_name)
    logger.info("YOLO model loaded successfully")
    return model


def detect_objects(jpeg_bytes: bytes) -> list[Detection]:
    """Run YOLO inference on a JPEG frame.

    Args:
        jpeg_bytes: Raw JPEG image bytes from the webcam.

    Returns:
        List of Detection objects found in the frame.
    """
    # Decode JPEG to numpy array
    arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        logger.warning("Failed to decode JPEG frame")
        return []

    model = _load_model()
    results = model(frame, conf=settings.yolo_confidence, verbose=False)

    detections: list[Detection] = []
    for result in results:
        for box in result.boxes:
            cls_id = int(box.cls[0])
            class_name = model.names[cls_id]
            confidence = float(box.conf[0])
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            detections.append(Detection(
                class_name=class_name,
                confidence=confidence,
                bbox=(int(x1), int(y1), int(x2), int(y2)),
            ))

    return detections
