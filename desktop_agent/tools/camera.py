"""Open Windows Camera for preview; invoke its photo shutter only on a separate request."""

import ctypes
import os
import re
import time
from pathlib import Path
from uuid import UUID

PHOTO_SHUTTER = re.compile(
    r"^(?:拍照|拍\s*摄\s*照片|拍攝\s*相片|拍攝\s*照片|take\s+(?:a\s+)?photo)"
    r"(?:\s*[（(].*[)）])?$",
    re.I,
)
PHOTO_MODE = re.compile(
    r"^(?:照片|相片|photo|切换到\s*照片\s*模式|切換(?:至|到)\s*(?:相片|照片)\s*模式|"
    r"switch\s+to\s+photo\s+mode)$",
    re.I,
)


def process_name(pid):
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return ""
        return Path(buffer.value).name.casefold()
    finally:
        kernel.CloseHandle(handle)


def camera_roll():
    """Resolve the actual Windows Camera Roll known folder, including redirection."""
    from ctypes import wintypes

    shell = ctypes.WinDLL("shell32")
    ole = ctypes.WinDLL("ole32")
    shell.SHGetKnownFolderPath.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.HANDLE,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    shell.SHGetKnownFolderPath.restype = ctypes.c_long
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    folder_id = ctypes.create_string_buffer(UUID("AB5FB87B-7CE2-4F83-915D-550846C9537B").bytes_le)
    result = ctypes.c_void_p()
    status = shell.SHGetKnownFolderPath(folder_id, 0, None, ctypes.byref(result))
    if status != 0:
        raise RuntimeError("无法定位系统相册。请在 .env 配置 CAMERA_ROLL_DIR 为相机的保存目录。")
    try:
        return Path(ctypes.wstring_at(result))
    finally:
        ole.CoTaskMemFree(result)


class CameraTools:
    def __init__(self, roll_dir=None):
        self.roll_dir = roll_dir

    def _find(self):
        from pywinauto import Desktop

        matches = []
        for window in Desktop(backend="win32").windows(
            title_re=r"^(?:相机|相機|Camera|Windows Camera)$"
        ):
            owner = process_name(window.process_id())
            if owner in {"windowscamera.exe", "applicationframehost.exe"}:
                matches.append(window)
        if len(matches) > 1:
            raise RuntimeError("发现多个相机窗口，请先保留一个相机窗口。")
        if not matches:
            return None
        return Desktop(backend="uia").window(handle=matches[0].handle).wrapper_object()

    @property
    def active(self):
        return self._find() is not None

    def open(self):
        window = self._find()
        if window is None:
            # Registered by Microsoft's Camera package; never opens the Settings app.
            try:
                os.startfile("microsoft.windows.camera:")
            except OSError as error:
                raise RuntimeError(
                    "Windows 相机启动失败，请确认已安装 Microsoft 相机应用。"
                ) from error
            deadline = time.monotonic() + 12
            while window is None and time.monotonic() < deadline:
                time.sleep(0.2)
                window = self._find()
        if window is None:
            raise RuntimeError("未找到 Windows 相机窗口，请检查是否有首次启动或权限提示。")
        if window.is_minimized():
            window.restore()
        window.set_focus()
        return "已打开 Windows 相机，请在窗口中查看预览；说“拍照”后才会按快门。"

    @staticmethod
    def _button(window, pattern):
        matches = [
            button
            for button in window.descendants(control_type="Button")
            if button.is_visible()
            and button.is_enabled()
            and pattern.fullmatch(button.window_text().strip())
        ]
        if len(matches) > 1:
            raise RuntimeError("相机按钮不唯一，已停止，避免误操作。")
        return matches[0] if matches else None

    def _shutter(self, window):
        shutter = self._button(window, PHOTO_SHUTTER)
        if shutter is not None:
            return shutter
        # Microsoft's Camera uses separate mode and shutter buttons. Never invoke
        # a generic CaptureButton ID: that same ID can mean video recording.
        mode = self._button(window, PHOTO_MODE)
        if mode is None:
            names = [
                button.window_text().strip()
                for button in window.descendants(control_type="Button")
                if button.is_visible() and button.is_enabled()
            ]
            raise RuntimeError(
                f"找不到相机“拍照”按钮。请检查相机是否有权限或占用提示。当前可用按钮：{names}"
            )
        mode.invoke()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            time.sleep(0.15)
            shutter = self._button(window, PHOTO_SHUTTER)
            if shutter is not None:
                return shutter
        raise RuntimeError("相机尚未进入照片模式，本次没有按快门。")

    @staticmethod
    def _photos(folder):
        found = {}
        if not folder.is_dir():
            return found
        for path in folder.iterdir():
            if path.suffix.casefold() in {".jpg", ".jpeg", ".png", ".heic", ".webp"}:
                try:
                    stat = path.stat()
                    if stat.st_size:
                        found[path] = (stat.st_mtime_ns, stat.st_size)
                except OSError:
                    continue
        return found

    def take_photo(self):
        window = self._find()
        if window is None:
            raise RuntimeError("相机还没有打开。请先说“打开相机”，看到预览后再说“拍照”。")
        if window.is_minimized():
            window.restore()
        window.set_focus()
        folder = Path(self.roll_dir) if self.roll_dir else camera_roll()
        shutter = self._shutter(window)
        previous = self._photos(folder)
        shutter.invoke()  # Exactly once; no automatic retry after a possible capture.
        deadline = time.monotonic() + 15  # Allows the app's optional countdown timer.
        while time.monotonic() < deadline:
            time.sleep(0.25)
            current = self._photos(folder)
            changed = [
                path for path, fingerprint in current.items() if previous.get(path) != fingerprint
            ]
            if changed:
                newest = max(changed, key=lambda path: current[path][0])
                return f"Windows 相机已拍照，新照片：{newest}。相机继续保持打开。"
        raise RuntimeError(
            "已按一次相机快门，但未在相册确认新照片；不会自动重拍。"
            "请查看相机右下角缩略图；如修改过保存位置，请设置 CAMERA_ROLL_DIR。"
        )
