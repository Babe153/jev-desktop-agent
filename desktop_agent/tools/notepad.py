import subprocess
import time
from uuid import uuid4


class NotepadTools:
    """Track one uniquely named document, including Windows 11 tabbed Notepad."""

    def __init__(self, files, confirm):
        self.files = files
        self.confirm = confirm
        self.path = None
        self.window = None
        self.dirty = False

    def _find(self):
        from pywinauto import Desktop

        if not self.path:
            return None
        for window in Desktop(backend="uia").windows(class_name="Notepad"):
            if self.path.name in window.window_text():
                return window
        return None

    @property
    def active(self):
        return self._find() is not None

    def _editor(self):
        window = self._find()
        if window is None:
            raise RuntimeError("找不到助手的记事本文档，请先打开记事本。")
        self.window = window
        editors = window.descendants(control_type="Document")
        if not editors:
            editors = window.descendants(control_type="Edit")
        editors = [editor for editor in editors if editor.is_visible()]
        if len(editors) != 1:
            raise RuntimeError("无法唯一识别记事本编辑区，已停止，避免输入到错误位置。")
        return editors[0]

    def open(self, path=None):
        if self.active:
            if path is None or path == self.path:
                self._find().set_focus()
                return f"记事本已打开：{self.path.name}"
            self.close()
        if path is None:
            path = self.files.write(f"草稿-{uuid4().hex[:8]}.txt", "", exclusive=True)
        self.path = path
        subprocess.Popen(["notepad.exe", str(path)])
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            self.window = self._find()
            if self.window:
                self._editor()
                self.dirty = False
                return f"记事本已打开：{path}"
            time.sleep(0.2)
        raise RuntimeError("记事本启动超时；请检查窗口是否被对话框阻挡。")

    @staticmethod
    def _text(editor):
        try:
            return editor.get_value()
        except Exception:
            return editor.iface_text.DocumentRange.GetText(-1)

    def write(self, text):
        from pywinauto.uia_defines import NoPatternInterfaceError

        if not self.active:
            self.open()
        editor = self._editor()
        previous = self._text(editor)
        expected = previous + text
        self.window.set_focus()
        # Document wrappers do not expose set_edit_text; address ValuePattern directly.
        try:
            editor.iface_value.SetValue(expected)
        except NoPatternInterfaceError:
            # Some Windows 11 versions expose TextPattern without ValuePattern.
            # Escape pywinauto's key grammar so user text stays literal.
            escaped = "".join(
                "{ENTER}"
                if char == "\n"
                else "{TAB}"
                if char == "\t"
                else "{" + char + "}"
                if char in "+^%~(){}"
                else char
                for char in text.replace("\r\n", "\n")
            )
            editor.set_focus()
            editor.type_keys("^{END}")
            editor.type_keys(escaped, with_spaces=True, pause=0.002, vk_packet=True)
        self.dirty = True
        actual = self._text(self._editor())
        if actual.replace("\r\n", "\n") != expected.replace("\r\n", "\n"):
            raise RuntimeError("记事本输入校验失败，请检查窗口内容。")
        return f"已在记事本追加 {len(text)} 字。尚未保存，请说“保存为：笔记.txt”。"

    def save(self, name):
        text = self._text(self._editor())
        target = self.files.write(name, text)
        # Export a snapshot without silently changing the open document or clearing
        # Notepad's native dirty state. Closing may still show its save prompt.
        return f"编辑区内容已导出并校验：{target}（原记事本标签不变，关闭时仍可能提示保存）"

    def close(self):
        window = self._find()
        if window is None:
            return "助手的记事本文档已经关闭。"
        if not self.confirm("关闭助手的记事本标签？\n未保存内容将由记事本提示处理。"):
            raise RuntimeError("已取消关闭。")
        window.set_focus()
        window.type_keys("^w")  # Close only tracked document/tab, never kill the process.
        time.sleep(0.3)
        if self._find() is not None:
            raise RuntimeError("记事本文档仍在打开；请处理保存对话框后重试。")
        self.path = self.window = None
        self.dirty = False
        return "助手记事本标签已关闭。"
