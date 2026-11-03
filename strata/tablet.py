"""Input capture only; no brush evaluation or GPU calls.

Windows Ink pressure accompanies GLFW's promoted mouse position/buttons. Other
platforms, devices without pressure, and ordinary mice use pressure 1.0.
"""
from __future__ import annotations

import math
import sys


class TabletInput:
    def __init__(self):
        self.pressure = 1.0
        self.source = "mouse"
        self.status = "Mouse fallback (pressure 1.0)"
        self._hook = None

    def pen(self, raw_pressure, has_pressure=True):
        value = float(raw_pressure) / 1024 if has_pressure else 1.0
        self.pressure = max(0.0, min(1.0, value)) if math.isfinite(value) else 1.0
        self.source = "pen"

    def mouse(self):
        self.pressure, self.source = 1.0, "mouse"

    def attach(self, window):
        if sys.platform != "win32":
            return
        try:
            import glfw
            self._hook = _WindowsPen(glfw.get_win32_window(window), self)
            self.status = "Windows Ink ready (hardware unverified)"
        except (AttributeError, OSError) as exc:
            self.status = f"Mouse fallback: {exc}"

    def close(self):
        if self._hook is not None:
            self._hook.close()
            self._hook = None
        self.mouse()


class _WindowsPen:
    """Observe pointer messages, then always forward to GLFW for mouse promotion."""
    def __init__(self, hwnd, state):
        import ctypes as C
        from ctypes import wintypes as W

        class PointerInfo(C.Structure):
            _fields_ = [(n, t) for n, t in (
                ("pointerType", W.UINT), ("pointerId", W.UINT), ("frameId", W.UINT),
                ("pointerFlags", W.UINT), ("sourceDevice", W.HANDLE), ("hwndTarget", W.HWND),
                ("ptPixelLocation", W.POINT), ("ptHimetricLocation", W.POINT),
                ("ptPixelLocationRaw", W.POINT), ("ptHimetricLocationRaw", W.POINT),
                ("dwTime", W.DWORD), ("historyCount", W.UINT), ("InputData", W.INT),
                ("dwKeyStates", W.DWORD), ("PerformanceCount", C.c_uint64), ("ButtonChangeType", W.UINT))]

        class PenInfo(C.Structure):
            _fields_ = [("pointerInfo", PointerInfo), ("penFlags", W.UINT), ("penMask", W.UINT),
                        ("pressure", W.UINT), ("rotation", W.UINT), ("tiltX", W.INT), ("tiltY", W.INT)]

        self.hwnd, self.state = hwnd, state
        self.api = C.WinDLL("user32", use_last_error=True)
        self.get_pen = self.api.GetPointerPenInfo
        self.get_pen.argtypes, self.get_pen.restype = [W.UINT, C.POINTER(PenInfo)], W.BOOL
        self.set_proc = getattr(self.api, "SetWindowLongPtrW" if C.sizeof(C.c_void_p) == 8 else "SetWindowLongW")
        self.set_proc.argtypes, self.set_proc.restype = [W.HWND, C.c_int, C.c_void_p], C.c_void_p
        self.call_proc = self.api.CallWindowProcW
        self.call_proc.argtypes = [C.c_void_p, W.HWND, W.UINT, C.c_size_t, C.c_ssize_t]
        self.call_proc.restype = C.c_ssize_t
        self.api.GetMessageExtraInfo.restype = C.c_ssize_t
        self.info_type = PenInfo
        callback = C.WINFUNCTYPE(C.c_ssize_t, W.HWND, W.UINT, C.c_size_t, C.c_ssize_t)

        def observe(hwnd, msg, wp, lp):
            # Never let a capture failure prevent the original window procedure.
            try:
                self.message(msg, wp)
            except Exception:
                state.mouse()
            return self.call_proc(self.previous, hwnd, msg, wp, lp)

        self.callback = callback(observe)  # retain until the window procedure is restored
        C.set_last_error(0)
        self.previous = self.set_proc(hwnd, -4, C.cast(self.callback, C.c_void_p))
        if not self.previous:
            raise C.WinError(C.get_last_error())

    def message(self, msg, wp):
        import ctypes as C
        if msg in (0x0245, 0x0246, 0x0247):  # UPDATE, DOWN, UP
            info = self.info_type()
            if self.get_pen(wp & 0xffff, C.byref(info)):
                if msg != 0x0247 and info.pointerInfo.pointerFlags & 0x4:  # INCONTACT
                    self.state.pen(info.pressure, bool(info.penMask & 1))
                # Keep the last contact value until promoted release is processed.
            else:
                self.state.mouse()
        elif msg in (0x0200, 0x0201):  # real mouse move/down; ignore promoted pen/touch
            extra = self.api.GetMessageExtraInfo()
            if extra & 0xffffff00 != 0xff515700:
                self.state.mouse()
        elif msg in (0x0008, 0x024c, 0x024a):  # focus/capture loss, pointer leave
            self.state.mouse()

    def close(self):
        import ctypes as C
        C.set_last_error(0)
        if not self.set_proc(self.hwnd, -4, self.previous) and C.get_last_error():
            raise C.WinError(C.get_last_error())
