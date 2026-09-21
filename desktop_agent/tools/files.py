import os
import tempfile
from pathlib import Path


class FileTools:
    def __init__(self, root: Path, confirm):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.confirm = confirm

    def resolve(self, name: str) -> Path:
        if not name.strip() or ":" in name or "\x00" in name:
            raise ValueError("使用工作目录内的相对文件名，例如：笔记.txt")
        path = (self.root / name).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise ValueError("文件必须位于工作目录内。")
        if path.suffix.lower() not in {".txt", ".md", ".csv", ".json", ".log"}:
            raise ValueError("支持的文本文件：.txt .md .csv .json .log")
        for component in path.relative_to(self.root).parts:
            reserved = {"CON", "PRN", "AUX", "NUL"} | {
                f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
            }
            if component.split(".")[0].upper() in reserved:
                raise ValueError("文件名是 Windows 保留名称。")
            if any(c in component for c in '<>"|?*') or component.endswith((" ", ".")):
                raise ValueError("文件名包含无效字符。")
        return path

    def read(self, name: str) -> str:
        path = self.resolve(name)
        if path.stat().st_size > 1_000_000:
            raise ValueError("演示只读取 1 MB 以内的文本文件。")
        return path.read_text(encoding="utf-8-sig")

    def write(self, name: str, text: str, append=False, exclusive=False) -> Path:
        path = self.resolve(name)
        if path.exists():
            if exclusive:
                raise FileExistsError(f"文件已存在：{path.name}")
            if not append and not self.confirm(f"覆盖现有文件？\n{path}"):
                raise RuntimeError("已取消覆盖。")
        path.parent.mkdir(parents=True, exist_ok=True)
        if append or exclusive or not path.exists():
            mode = "a" if append else "x"
            with path.open(mode, encoding="utf-8", newline="") as stream:
                stream.write(text)
        else:
            fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
                    stream.write(text)
                os.replace(temporary, path)
            finally:
                Path(temporary).unlink(missing_ok=True)
        if not append and path.read_text(encoding="utf-8") != text.replace("\r\n", "\n"):
            raise RuntimeError("文件内容校验失败。")
        return path
