"""Scene change detection logic.

Compares YOLO detection snapshots across frames to decide when
to invoke the expensive OpenAI Vision API.
"""

import time
import logging
from collections import Counter
from dataclasses import dataclass, field

from config import settings
from vision.detector import Detection

logger = logging.getLogger(__name__)

# Type alias: maps class name → count
SceneSnapshot = Counter


@dataclass
class ChangeDetectorState:
    """Per-connection state for change detection."""
    last_snapshot: SceneSnapshot = field(default_factory=Counter)
    last_llm_call_time: float = 0.0
    is_first_frame: bool = True


def build_snapshot(detections: list[Detection]) -> SceneSnapshot:
    """Build a scene snapshot (class → count) from detections."""
    return Counter(d.class_name for d in detections)


def should_invoke_llm(
    snapshot: SceneSnapshot, state: ChangeDetectorState
) -> tuple[bool, str]:
    """Decide whether the current frame warrants an OpenAI Vision API call.

    Rules checked in order:
    1. First frame → always analyze (establishes baseline)
    2. Cooldown → skip if too recent
    3. Empty ↔ occupied transition
    4. New object class appeared
    5. Object class disappeared
    6. Total object count changed by ≥ 2

    Args:
        snapshot: Current frame's SceneSnapshot.
        state: Mutable per-connection state (updated on trigger).

    Returns:
        (should_call, reason) — reason is empty string if should_call is False.
    """
    now = time.time()

    # Rule 1: First frame
    if state.is_first_frame:
        state.is_first_frame = False
        state.last_snapshot = snapshot
        state.last_llm_call_time = now
        return True, "first_frame"

    # Rule 2: Cooldown
    elapsed = now - state.last_llm_call_time
    if elapsed < settings.vision_change_cooldown:
        return False, ""

    prev = state.last_snapshot
    prev_total = sum(prev.values())
    curr_total = sum(snapshot.values())

    prev_classes = set(prev.keys())
    curr_classes = set(snapshot.keys())

    # Rule 3: Empty ↔ occupied
    if (prev_total == 0) != (curr_total == 0):
        reason = "scene_empty" if curr_total == 0 else "scene_occupied"
        state.last_snapshot = snapshot
        state.last_llm_call_time = now
        return True, reason

    # Rule 4: New class appeared
    new_classes = curr_classes - prev_classes
    if new_classes:
        state.last_snapshot = snapshot
        state.last_llm_call_time = now
        return True, f"new_objects: {new_classes}"

    # Rule 5: Class disappeared
    gone_classes = prev_classes - curr_classes
    if gone_classes:
        state.last_snapshot = snapshot
        state.last_llm_call_time = now
        return True, f"objects_gone: {gone_classes}"

    # Rule 6: Count shift ≥ 2
    if abs(curr_total - prev_total) >= 2:
        state.last_snapshot = snapshot
        state.last_llm_call_time = now
        return True, f"count_shift: {prev_total} -> {curr_total}"

    return False, ""
