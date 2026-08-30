"""linkerbot_o6.can_adapter — userspace PCAN-USB driver.

Drives PCAN-USB-compatible adapters (PEAK System 0x0c72:0x000c, e.g. the
XCAN-USB clone) directly via libusb (ctypes). No vendor kernel drivers needed.

Protocol reference: Linux kernel drivers/net/can/usb/peak_usb/pcan_usb.c
"""
import ctypes
import ctypes.util
import time

VID, PID = 0x0C72, 0x000C
EP_CMD_OUT, EP_CMD_IN = 0x01, 0x81
EP_MSG_OUT, EP_MSG_IN = 0x02, 0x82
BUF = 64

# SJA1000 BTR0/BTR1 for 16 MHz crystal (standard PCAN values)
BITRATES = {
    1000: (0x00, 0x14),
    800:  (0x00, 0x16),
    500:  (0x00, 0x1C),
    250:  (0x01, 0x1C),
    125:  (0x03, 0x1C),
    100:  (0x04, 0x1C),
    50:   (0x09, 0x1C),
    20:   (0x18, 0x1C),
    10:   (0x31, 0x1C),
}

CMD_BITRATE, CMD_SET_BUS, CMD_DEVID, CMD_SN, CMD_REGISTER, CMD_ERR_FR = 1, 3, 4, 6, 9, 11
GET, SET = 1, 2
BUS_XCVER = 2
SJA_INIT, SJA_NORMAL = 1, 0
BERR_MASK = 0x06

SL_TS, SL_INTERNAL, SL_EXT, SL_RTR, SL_DLC = 0x80, 0x40, 0x20, 0x10, 0x0F
TX_SRR = 0x01

libusb = ctypes.CDLL(ctypes.util.find_library("usb-1.0") or "libusb-1.0.dylib")
libusb.libusb_init.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
libusb.libusb_init.restype = ctypes.c_int
libusb.libusb_open_device_with_vid_pid.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_uint16]
libusb.libusb_open_device_with_vid_pid.restype = ctypes.c_void_p
libusb.libusb_claim_interface.argtypes = [ctypes.c_void_p, ctypes.c_int]
libusb.libusb_claim_interface.restype = ctypes.c_int
libusb.libusb_release_interface.argtypes = [ctypes.c_void_p, ctypes.c_int]
libusb.libusb_release_interface.restype = ctypes.c_int
libusb.libusb_bulk_transfer.argtypes = [ctypes.c_void_p, ctypes.c_uint8, ctypes.POINTER(ctypes.c_ubyte),
                                        ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.c_uint]
libusb.libusb_bulk_transfer.restype = ctypes.c_int
libusb.libusb_close.argtypes = [ctypes.c_void_p]
libusb.libusb_exit.argtypes = [ctypes.c_void_p]
libusb.libusb_reset_device.argtypes = [ctypes.c_void_p]
libusb.libusb_reset_device.restype = ctypes.c_int
libusb.libusb_clear_halt.argtypes = [ctypes.c_void_p, ctypes.c_uint8]
libusb.libusb_clear_halt.restype = ctypes.c_int
libusb.libusb_error_name.argtypes = [ctypes.c_int]
libusb.libusb_error_name.restype = ctypes.c_char_p

LIBUSB_ERROR_TIMEOUT = -7
LIBUSB_ERROR_PIPE = -9
LIBUSB_ERROR_NO_DEVICE = -4


def err_name(r):
    try:
        return libusb.libusb_error_name(r).decode()
    except Exception:
        return str(r)


class CanAdapter:
    """A PCAN-USB compatible adapter (SJA1000)."""

    def __init__(self, vid=VID, pid=PID):
        self.ctx = ctypes.c_void_p()
        r = libusb.libusb_init(ctypes.byref(self.ctx))
        if r != 0:
            raise RuntimeError(f"libusb_init failed: {err_name(r)}")
        self.dev = libusb.libusb_open_device_with_vid_pid(self.ctx, vid, pid)
        if not self.dev:
            libusb.libusb_exit(self.ctx)
            raise RuntimeError(f"PCAN-USB (0x{vid:04x}:0x{pid:04x}) not found")
        r = libusb.libusb_claim_interface(self.dev, 0)
        if r != 0:
            libusb.libusb_close(self.dev)
            libusb.libusb_exit(self.ctx)
            raise RuntimeError(f"claim_interface failed: {err_name(r)}")
        self.tx_cnt = 0

    def close(self):
        if getattr(self, "dev", None):
            libusb.libusb_release_interface(self.dev, 0)
            libusb.libusb_close(self.dev)
            self.dev = None
        libusb.libusb_exit(self.ctx)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def reset_device(self):
        """USB-level reset (re-enumerates the adapter)."""
        libusb.libusb_release_interface(self.dev, 0)
        r = libusb.libusb_reset_device(self.dev)
        if r != 0:
            raise RuntimeError(f"libusb_reset_device: {err_name(r)}")
        r = libusb.libusb_claim_interface(self.dev, 0)
        if r != 0:
            raise RuntimeError(f"re-claim after reset failed: {err_name(r)}")

    def _bulk_out(self, ep, data, timeout=1000):
        buf = (ctypes.c_ubyte * BUF)(*data, *([0] * (BUF - len(data))))
        transferred = ctypes.c_int()
        r = libusb.libusb_bulk_transfer(self.dev, ep, buf, BUF,
                                        ctypes.byref(transferred), timeout)
        if r != 0 and r != LIBUSB_ERROR_TIMEOUT:
            raise RuntimeError(f"bulk OUT ep 0x{ep:02x}: {err_name(r)}")
        return r

    def _bulk_in(self, ep, timeout=1000):
        buf = (ctypes.c_ubyte * BUF)()
        transferred = ctypes.c_int()
        r = libusb.libusb_bulk_transfer(self.dev, ep, buf, BUF,
                                        ctypes.byref(transferred), timeout)
        if r == LIBUSB_ERROR_PIPE:
            libusb.libusb_clear_halt(self.dev, ep)
            r = libusb.libusb_bulk_transfer(self.dev, ep, buf, BUF,
                                            ctypes.byref(transferred), timeout)
        if r != 0 and r != LIBUSB_ERROR_TIMEOUT and r != LIBUSB_ERROR_NO_DEVICE:
            raise RuntimeError(f"bulk IN ep 0x{ep:02x}: {err_name(r)}")
        return r, bytes(buf[:transferred.value])

    # ---- commands ----
    def cmd(self, f, n, args=None):
        args = (args or [0] * 14)[:14]
        args += [0] * (14 - len(args))
        return self._bulk_out(EP_CMD_OUT, bytes([f, n]) + bytes(args))

    def cmd_rsp(self, f, n):
        self.cmd(f, n)
        r, data = self._bulk_in(EP_CMD_IN, timeout=1000)
        return data

    def get_serial(self):
        data = self.cmd_rsp(CMD_SN, GET)
        if len(data) >= 6:
            return int.from_bytes(data[2:6], "little")
        return None

    def set_sja(self, mode):
        self.cmd(CMD_REGISTER, SET, [0, mode])

    def set_bus(self, on):
        self.cmd(CMD_SET_BUS, BUS_XCVER, [1 if on else 0])

    def set_bitrate(self, kbps):
        btr0, btr1 = BITRATES[kbps]
        self.cmd(CMD_BITRATE, SET, [btr1, btr0])

    def set_err_frame(self, mask=BERR_MASK):
        self.cmd(CMD_ERR_FR, SET, [mask])

    def bring_up(self, kbps):
        """Init sequence: bus off -> SJA1000 init mode -> bitrate -> bus on."""
        self.set_bus(False)
        self.set_sja(SJA_INIT)
        self.set_bitrate(kbps)
        self.set_bus(True)
        time.sleep(0.02)
        self.set_err_frame()

    def send_frame(self, can_id, data=b"", ext=False, rtr=False):
        dlc = min(len(data), 8)
        pkt = bytearray(64)
        pkt[0] = 2  # PCAN_USB_MSG_TX_CAN
        pkt[1] = 1  # one frame
        sl = dlc
        if rtr:
            sl |= SL_RTR
        if ext:
            sl |= SL_EXT
            pkt[2] = sl
            pkt[3:7] = ((can_id << 3) & 0xFFFFFFFF).to_bytes(4, "little")
            off = 7
        else:
            pkt[2] = sl
            pkt[3:5] = ((can_id << 5) & 0xFFFF).to_bytes(2, "little")
            off = 5
        if not rtr:
            pkt[off:off + dlc] = bytes(data[:dlc])
        self.tx_cnt = (self.tx_cnt + 1) & 0xFF
        pkt[63] = self.tx_cnt
        buf = (ctypes.c_ubyte * BUF)(*pkt)
        transferred = ctypes.c_int()
        r = libusb.libusb_bulk_transfer(self.dev, EP_MSG_OUT, buf, BUF,
                                        ctypes.byref(transferred), 1000)
        return r == 0

    # ---- RX decoding ----
    def decode(self, buf):
        out = []
        if len(buf) < 2:
            return out
        rec_cnt = buf[1]
        ptr = 2
        ts_idx = 0
        for _ in range(rec_cnt):
            if ptr >= len(buf):
                break
            sl = buf[ptr]
            ptr += 1
            if sl & SL_INTERNAL:
                if ptr + 2 > len(buf):
                    break
                f, n = buf[ptr], buf[ptr + 1]
                ptr += 2
                if sl & SL_TS:
                    ptr += 2 if ts_idx == 0 else 1
                    ts_idx += 1
                rec_len = sl & SL_DLC
                if f == 2:
                    rec_len = 2
                elif f == 3:
                    rec_len = 1
                if ptr + rec_len > len(buf):
                    break
                payload = buf[ptr:ptr + rec_len]
                ptr += rec_len
                out.append(("status", f, n, payload))
            else:
                ext = bool(sl & SL_EXT)
                rtr = bool(sl & SL_RTR)
                dlc = sl & SL_DLC
                if ext:
                    if ptr + 4 > len(buf):
                        break
                    idf = int.from_bytes(buf[ptr:ptr + 4], "little")
                    ptr += 4
                    can_id = idf >> 3
                else:
                    if ptr + 2 > len(buf):
                        break
                    idf = int.from_bytes(buf[ptr:ptr + 2], "little")
                    ptr += 2
                    can_id = idf >> 5
                ptr += 2 if ts_idx == 0 else 1
                ts_idx += 1
                data = b""
                if not rtr:
                    if ptr + dlc > len(buf):
                        break
                    data = buf[ptr:ptr + dlc]
                    ptr += dlc
                if idf & TX_SRR and ptr < len(buf):
                    ptr += 1
                out.append(("frame", can_id, data, ext, rtr))
        return out

    def listen(self, seconds, quiet=True, quiet_status=True):
        frames = []
        end = time.time() + seconds
        while time.time() < end:
            r, data = self._bulk_in(EP_MSG_IN, timeout=int((end - time.time()) * 1000) + 50)
            if r == LIBUSB_ERROR_TIMEOUT or not data:
                continue
            for rec in self.decode(data):
                if rec[0] == "frame":
                    frames.append(rec)
                    if not quiet:
                        _, cid, d, ext, rtr = rec
                        flags = ("EXT " if ext else "") + ("RTR" if rtr else "")
                        print(f"  {flags}id=0x{cid:03X} [{len(d)}] " + " ".join(f"{b:02X}" for b in d))
        return frames


# Backwards-compatible alias
PCANUSB = CanAdapter
