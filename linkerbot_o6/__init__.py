"""linkerbot_o6 — zero-dependency SDK for the LinkerBot / LinkerHand O6 hand."""
from .hand import (
    LinkerHand,
    PRESETS_RAW,
    JOINTS,
    CAN_LEFT,
    CAN_RIGHT,
    grasp_pose,
    pct_to_raw,
    raw_to_pct,
)

__version__ = "0.1.0"
__all__ = [
    "LinkerHand",
    "PRESETS_RAW",
    "JOINTS",
    "CAN_LEFT",
    "CAN_RIGHT",
    "grasp_pose",
    "pct_to_raw",
    "raw_to_pct",
    "__version__",
]
