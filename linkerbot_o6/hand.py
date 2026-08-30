"""linkerbot_o6.hand — LinkerHand O6 high-level API.

CAN protocol (from the public linkerhand SDKs):
1 Mbit/s, standard 11-bit arbitration ID 0x28 (left) / 0x27 (right),
data[0] = command byte. Angles are 0-100 percent (higher = finger extends);
hardware raw scale is 0-255.
"""
import time

from .can_adapter import CanAdapter

CAN_LEFT, CAN_RIGHT = 0x28, 0x27
JOINTS = ["thumb_flex", "thumb_abd", "index", "middle", "ring", "pinky"]

# Raw 0-255 presets (from linkerhand-ros-sdk O6_positions.yaml, LEFT_HAND)
PRESETS_RAW = {
    "open": [255, 179, 255, 255, 255, 255],
    "fist": [67, 151, 0, 0, 0, 0],
    "thumbs_up": [255, 179, 0, 0, 0, 0],
    "v_sign": [67, 151, 255, 255, 0, 0],
    "point": [67, 151, 255, 0, 0, 0],
    "middle": [67, 151, 0, 255, 0, 0],
    "rock_on": [67, 151, 255, 0, 0, 255],
}

DEFAULT_SPEED = 50
DEFAULT_TORQUE = 180


def pct_to_raw(vals):
    return [max(0, min(255, round(v * 255 / 100))) for v in vals]


def raw_to_pct(vals):
    return [round(v * 100 / 255) for v in vals]


def grasp_pose(ball_cm):
    """Ball-grasp pose in percent for a ball of given diameter (cm).
    Bigger ball -> fingers/thumb less curled. The thumb wraps over the ball.
    Returns [thumb_flex, thumb_abd, index, middle, ring, pinky]."""
    d = max(2.0, min(14.0, ball_cm))
    fingers = max(15, min(70, round(15 + (d - 3) * 5.6)))
    thumb_f = max(28, min(60, round(28 + (d - 3) * 3.5)))
    thumb_a = max(52, min(72, round(52 + (d - 3) * 2)))
    return [thumb_f, thumb_a, fingers, fingers, fingers, fingers]


class LinkerHand:
    """A LinkerHand O6 connected via a PCAN-USB-compatible adapter."""

    def __init__(self, side="left", bitrate=1000):
        self.can_id = CAN_LEFT if side == "left" else CAN_RIGHT
        self.side = side
        self.bitrate = bitrate
        self.adapter = CanAdapter()
        self.adapter.bring_up(bitrate)

    def close(self):
        try:
            self.adapter.set_bus(False)
        finally:
            self.adapter.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---- internal ----
    def _send(self, cmd, payload):
        self.adapter._bulk_in(0x82, timeout=50)  # drain stale
        self.adapter.send_frame(self.can_id, bytes([cmd] + list(payload)))

    def query(self, cmd, wait=0.08, listen=0.2, retries=2):
        """Send a read-only query, return payload bytes after the cmd byte."""
        for _ in range(retries + 1):
            self._send(cmd, [])
            time.sleep(wait)
            for rec in self.adapter.listen(listen):
                if rec[0] == "frame":
                    _, rid, d, ext, rtr = rec
                    if rid == self.can_id and d and d[0] == cmd and len(d) > 1:
                        return d[1:]
        return None

    def query_all(self, cmd, wait=0.08, listen=0.4):
        """Send a query and collect ALL matching responses (some queries,
        e.g. serial, answer in indexed chunks)."""
        self._send(cmd, [])
        time.sleep(wait)
        hits = []
        for rec in self.adapter.listen(listen):
            if rec[0] == "frame":
                _, rid, d, ext, rtr = rec
                if rid == self.can_id and d and d[0] == cmd and len(d) > 1:
                    hits.append(d[1:])
        return hits

    # ---- read-only ----
    def get_serial(self):
        chunks = {}
        for h in self.query_all(0xC0):
            if h and h[0] in (0, 1, 2, 3):
                chunks[h[0]] = bytes(h[1:]).decode("ascii", "replace")
        serial = "".join(chunks.get(i, "") for i in range(4))
        return serial or None

    def get_positions(self):
        return self.query(0x01)

    def get_faults(self):
        return self.query(0x35)

    def get_temps(self):
        return self.query(0x33)

    def get_version(self):
        return self.query(0x64)

    # ---- motion ----
    def set_speed(self, speeds):
        self._send(0x05, speeds)
        time.sleep(0.02)

    def set_torque(self, torques):
        self._send(0x02, torques)
        time.sleep(0.02)

    def move_raw(self, raw, speed=None, torque=None):
        """Command joint positions (raw 0-255). Optionally set speed/torque first."""
        if speed is not None:
            self.set_speed([speed] * 6)
        if torque is not None:
            self.set_torque([torque] * 6)
        self._send(0x01, raw)
        time.sleep(0.05)

    def move(self, pct, speed=None, torque=None):
        self.move_raw(pct_to_raw(pct), speed=speed, torque=torque)

    def preset(self, name, speed=None):
        if name not in PRESETS_RAW:
            raise ValueError(f"unknown preset {name!r}; choose from {sorted(PRESETS_RAW)}")
        self.move_raw(list(PRESETS_RAW[name]), speed=speed)
        return list(PRESETS_RAW[name])

    def grasp(self, ball_cm=6.0, strength=150, speed=40):
        """Two-stage ball grasp: open wide -> fingers close -> thumb wraps over."""
        pose = grasp_pose(ball_cm)
        self.move_raw(pct_to_raw([100] * 6), speed=80)
        time.sleep(0.8)
        self.set_torque([strength] * 6)
        time.sleep(0.05)
        fingers_only = [90, pose[1], pose[2], pose[3], pose[4], pose[5]]
        self.move_raw(pct_to_raw(fingers_only), speed=speed)
        time.sleep(0.6)
        self.move_raw(pct_to_raw(pose), speed=speed)
        time.sleep(0.3)
        return pose

    def release(self, speed=60):
        self.move_raw(pct_to_raw([100] * 6), speed=speed)
        time.sleep(0.3)
