"""Only extract literal arguments; all action selection is performed by Jev."""

import re

QUOTES = {'"': '"', "“": "”", "「": "」"}


def split_steps(text: str) -> list[str]:
    # Preserve separators inside literal content, including full paragraphs.
    parts, buffer, closing = [], [], None
    i = 0
    while i < len(text):
        char = text[i]
        if closing:
            buffer.append(char)
            if char == closing:
                closing = None
            i += 1
            continue
        if char in QUOTES:
            closing = QUOTES[char]
            buffer.append(char)
            i += 1
            continue
        separator = next((s for s in ("然后", "接着", "；", ";") if text.startswith(s, i)), None)
        if separator:
            parts.append("".join(buffer).strip(" ，,。\n"))
            buffer = []
            i += len(separator)
        else:
            buffer.append(char)
            i += 1
    if closing:
        raise ValueError("引号未闭合。正文可用中文双引号包围。")
    parts.append("".join(buffer).strip(" ，,。\n"))
    parts = [part for part in parts if part]
    if not parts:
        raise ValueError("请先输入或录制一句指令。")
    if len(parts) > 10 or len(text) > 12000:
        raise ValueError("一次最多 10 步、12000 字，请拆分指令。")
    return parts


def clean(value: str) -> str:
    value = value.strip().rstrip("，。")
    for opening, closing in QUOTES.items():
        if value.startswith(opening) and value.endswith(closing):
            return value[1:-1]
    return value


def after(text: str, pattern: str) -> str | None:
    match = re.search(pattern + r"\s*[:：]?\s*(.+)$", text, re.S)
    return clean(match.group(1)) if match else None


def arguments(action: str, instruction: str) -> dict:
    if action == "notepad_write":
        content = after(instruction, r"(?:内容(?:是|为)?|写入|写上|输入|追加)")
        if content is None:
            raise ValueError("缺少正文。示例：在记事本写入：你好，世界")
        return {"text": content}
    if action in {"file_write", "file_append"}:
        match = re.search(
            r"文件\s*[:：]?\s*(.+?)[，,]\s*内容(?:是|为)?\s*[:：]?\s*(.+)$",
            instruction,
            re.DOTALL,
        )
        if not match:
            raise ValueError("文件写入格式：写入文件：笔记.txt，内容：你好")
        return {"path": clean(match.group(1)), "text": clean(match.group(2))}
    if action in {"file_read", "file_open", "file_create"}:
        path = after(instruction, r"文件")
        if not path:
            raise ValueError("请指定文件名，例如：打开文件：笔记.txt")
        return {"path": path}
    if action == "notepad_save":
        path = after(instruction, r"(?:保存为|保存到|另存为)")
        if not path:
            raise ValueError("请指定保存文件名，例如：保存为：笔记.txt")
        return {"path": path}
    if action == "browser_search":
        query = after(instruction, r"(?:搜索|查找)")
        if not query:
            raise ValueError("请指定搜索词，例如：搜索：Python 教程")
        return {"query": query}
    if action == "browser_open":
        match = re.search(r"https?://[^\s\"“”]+", instruction)
        return {"url": match.group(0).rstrip("，。") if match else "https://www.bing.com"}
    return {}
