from .browser import BrowserTools
from .camera import CameraTools
from .files import FileTools
from .notepad import NotepadTools

CRITERIA = {
    "notepad_open": "打开或新建记事本窗口，不含写字。",
    "notepad_write": "在记事本里输入或追加正文；未打开时自动打开。不是写磁盘文件。",
    "notepad_save": "把当前记事本正文保存为指定文件名。",
    "notepad_close": "关闭本助手打开的记事本标签，或关闭当前打开的文本文件。",
    "browser_open": "打开浏览器或访问明确的网址，不进行关键词搜索。",
    "browser_search": "在浏览器搜索指定关键词，必要时自动打开浏览器。",
    "browser_close": "关闭本助手打开的浏览器。",
    "file_create": "在磁盘创建一个空的文本文件。",
    "file_write": "在磁盘写入或覆盖指定文本文件的内容。",
    "file_append": "在磁盘指定文本文件末尾追加内容。",
    "file_read": "读取磁盘上的文本文件并显示内容。",
    "file_open": "用记事本打开指定的已有文本文件。",
    "camera_open": "只打开 Windows 相机软件并显示实时预览，不拍照。例：打开相机、打开摄像头、让我看看画面。",
    "camera_photo": "用户明确要求拍照或按快门，在已打开的相机中拍一张照片。例：拍照、拍一张。只说打开相机时不能选此项。",
    "unsupported": "指令含糊、仅聊天、请求生成正文、或不在上述功能内。",
}


class ToolRegistry:
    def __init__(self, config, confirm):
        self.config = config
        self.confirm = confirm
        self.files = FileTools(config.workspace, confirm)
        self.browser = BrowserTools()
        self.notepad = NotepadTools(self.files, confirm)
        self.camera = CameraTools(config.camera_roll_dir)

    def observe(self):
        return {
            "browser_open": self.browser.active,
            "notepad_open": self.notepad.active,
            "camera_open": self.camera.active,
            "notepad_document": self.notepad.path.name if self.notepad.path else None,
            "workspace": str(self.files.root),
        }

    def execute(self, name, args):
        if name == "notepad_open":
            return self.notepad.open()
        if name == "notepad_write":
            return self.notepad.write(args["text"])
        if name == "notepad_save":
            return self.notepad.save(args["path"])
        if name == "notepad_close":
            return self.notepad.close()
        if name == "browser_open":
            return self.browser.open(args["url"])
        if name == "browser_search":
            return self.browser.search(args["query"])
        if name == "browser_close":
            if self.browser.active and not self.confirm("关闭助手浏览器及其中的所有标签？"):
                raise RuntimeError("已取消关闭。")
            return self.browser.close()
        if name == "file_open":
            path = self.files.resolve(args["path"])
            if not path.is_file():
                raise FileNotFoundError(f"文件不存在：{path.name}")
            return self.notepad.open(path)
        if name == "file_read":
            return self.files.read(args["path"])
        if name in {"file_write", "file_append", "file_create"}:
            path = self.files.write(
                args["path"],
                args.get("text", ""),
                append=name == "file_append",
                exclusive=name == "file_create",
            )
            return f"文件已保存：{path}"
        if name == "camera_open":
            return self.camera.open()
        if name == "camera_photo":
            return self.camera.take_photo()
        raise ValueError("暂不支持这个请求，请使用界面上的示例口令。")

    def cleanup(self):
        self.browser.close()
        # Notepad stays open so unsaved work is not discarded on app exit.
