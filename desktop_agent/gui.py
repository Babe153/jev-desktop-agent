import queue
import threading
import tkinter as tk
from collections import deque
from tkinter import messagebox, ttk

from .agent import Agent
from .config import Config
from .continuous import ContinuousListener
from .jev_client import JevClient
from .tools.registry import ToolRegistry
from .voice import Transcriber

EXAMPLES = [
    "打开记事本；然后写入：“明天下午三点开会”；然后保存为：会议.txt",
    "打开浏览器；然后搜索：Python 教程",
    "关闭浏览器",
    "写入文件：笔记.txt，内容：“你好，世界”",
    "读取文件：笔记.txt",
    "打开文件：笔记.txt",
    "关闭记事本",
    "打开相机",
    "拍照",
]


class App:
    def __init__(self, root, config):
        self.root, self.config = root, config
        self.events, self.jobs = queue.Queue(), queue.Queue()
        self.cancelled, self.closing = threading.Event(), threading.Event()
        self.pending = deque()
        self.busy = False
        self.worker_ready = False
        self.listener = None
        self.session = 0
        self.last_final = 0
        self.latest_draft = 0
        self.transcriber = Transcriber(config)
        root.title("Jev · 语音桌面助手")
        root.geometry("920x780")
        root.minsize(760, 620)
        root.protocol("WM_DELETE_WINDOW", self.close)
        frame = ttk.Frame(root, padding=20)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(4, weight=1)
        ttk.Label(frame, text="和 Jev 说话", font=("Microsoft YaHei UI", 22, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            frame, text="持续监听 · 边说边显示 · 停顿后自动执行", font=("Microsoft YaHei UI", 11)
        ).grid(row=1, column=0, sticky="w", pady=(4, 12))
        self.status = tk.StringVar(value="正在初始化工具…")
        self.voice_status = tk.StringVar(value="麦克风已关闭 · 点击“开始对话”后持续监听")
        ttk.Label(frame, textvariable=self.status).grid(row=2, column=0, sticky="w")
        ttk.Label(frame, textvariable=self.voice_status, wraplength=700).grid(
            row=3, column=0, sticky="w", pady=(5, 10)
        )
        self.output = tk.Text(
            frame,
            height=1,
            width=1,
            state="disabled",
            wrap="word",
            font=("Microsoft YaHei UI", 11),
            padx=12,
            pady=12,
            background="#f7f8fa",
            relief="flat",
        )
        self.output.grid(row=4, column=0, sticky="nsew")
        self.output.tag_configure("user", foreground="#2455a4")
        self.output.tag_configure("assistant", foreground="#263238")
        self.output.tag_configure("notice", foreground="#805500")
        ttk.Label(frame, text="正在说的话 / 文字输入").grid(
            row=5, column=0, sticky="w", pady=(12, 4)
        )
        self.input = tk.Text(frame, height=3, width=1, wrap="word", font=("Microsoft YaHei UI", 12))
        self.input.grid(row=6, column=0, sticky="ew")
        self.input.bind("<Control-Return>", lambda event: self.submit())
        buttons = ttk.Frame(frame)
        buttons.grid(row=7, column=0, sticky="ew", pady=10)
        self.record_button = ttk.Button(buttons, text="开始对话", command=self.toggle_listening)
        self.record_button.pack(side="left")
        self.run_button = ttk.Button(buttons, text="发送文字", command=self.submit)
        self.run_button.pack(side="left", padx=8)
        ttk.Button(buttons, text="停止全部", command=self.cancel).pack(side="left")
        self.preview = tk.BooleanVar(value=False)
        ttk.Checkbutton(buttons, text="仅预览，不执行", variable=self.preview).pack(
            side="left", padx=12
        )
        combo = ttk.Combobox(frame, values=EXAMPLES, state="readonly")
        combo.set("口令示例（停止监听后可填入）")
        combo.grid(row=8, column=0, sticky="ew")
        combo.bind("<<ComboboxSelected>>", lambda event: self.set_input(combo.get()))
        ttk.Label(
            frame, text=f"Jev：{config.model} · 文件目录：{config.workspace}", wraplength=700
        ).grid(row=9, column=0, sticky="w", pady=(8, 0))
        self._append(
            "助手",
            "点击“开始对话”，说“打开浏览器”或“搜索 Python 教程”。停顿后自动发送，不用再点击执行。",
            "assistant",
        )
        self.thread = threading.Thread(target=self.worker, daemon=True)
        self.thread.start()
        self.refresh_controls()
        root.after(60, self.poll)

    def _append(self, speaker, text, tag="assistant"):
        self.output.config(state="normal")
        self.output.insert("end", f"{speaker}  {text}\n\n", tag)
        self.output.see("end")
        self.output.config(state="disabled")

    def _draft(self, text):
        self.input.config(state="normal")
        self.input.delete("1.0", "end")
        self.input.insert("1.0", text)
        if self.listener:
            self.input.config(state="disabled")

    def set_input(self, text):
        if not self.listener and not self.closing.is_set():
            self._draft(text)

    def log(self, text):
        self.events.put(("log", str(text)))

    def confirm(self, text):
        done, answer = threading.Event(), [False]
        self.events.put(("confirm", (text, done, answer)))
        while not done.wait(0.1):
            if self.closing.is_set() or self.cancelled.is_set():
                return False
        return answer[0] and not self.cancelled.is_set()

    def refresh_controls(self):
        enabled = self.worker_ready and not self.closing.is_set()
        self.record_button.config(
            state="normal" if enabled else "disabled",
            text="停止监听" if self.listener else "开始对话",
        )
        self.run_button.config(state="normal" if enabled and not self.listener else "disabled")
        self.input.config(state="disabled" if self.listener or self.closing.is_set() else "normal")

    def enqueue(self, text, source="text"):
        if not text.strip() or self.closing.is_set() or not self.worker_ready:
            return
        if len(self.pending) >= 3:
            self._append("提示", "已有三条指令等待执行，本句未发送。请等执行完成后再说。", "notice")
            return
        self._append("你", text, "user")
        self.pending.append((text, self.preview.get(), source))
        self.dispatch()

    def dispatch(self):
        if self.busy or not self.pending or self.closing.is_set() or not self.worker_ready:
            return
        text, preview, source = self.pending.popleft()
        self.cancelled.clear()
        self.busy = True
        self.status.set(f"Jev 正在处理… · 等待 {len(self.pending)} 条")
        self.jobs.put(("execute", (text, preview)))

    def submit(self):
        if not self.listener:
            text = self.input.get("1.0", "end").strip()
            self.enqueue(text)
            if text:
                self._draft("")

    def toggle_listening(self):
        if self.listener:
            self.stop_listening()
            return
        if not self.config.api_key:
            self._append("提示", "请先在 .env 设置 TYPESAFE_API_KEY，重启后开始对话。", "notice")
            return
        self.session += 1
        session = self.session
        self.last_final = self.latest_draft = 0
        self.listener = ContinuousListener(
            self.config,
            self.transcriber,
            lambda kind, payload: self.events.put(("voice", (session, kind, payload))),
        )
        self._draft("")
        self.voice_status.set("正在准备语音模型…")
        self.refresh_controls()
        self.listener.start()

    def stop_listening(self):
        if self.listener:
            self.listener.stop()
            self.listener = None
        self.session += 1
        self.pending = deque(job for job in self.pending if job[2] != "voice")
        self._draft("")
        self.voice_status.set("麦克风已关闭 · 未完成的语音和未执行的语音指令已丢弃")
        self.refresh_controls()

    def handle_voice(self, session, kind, payload):
        if session != self.session or self.listener is None or self.closing.is_set():
            return
        if kind == "loading":
            self.voice_status.set(payload)
        elif kind == "ready":
            self.voice_status.set(f"● 正在监听 · 停顿 {self.config.speech_silence:g} 秒后自动发送")
        elif kind in {"partial", "final"}:
            utterance, text = payload
            if utterance <= self.last_final:
                return
            if kind == "partial":
                if utterance >= self.latest_draft:
                    self.latest_draft = utterance
                    self._draft(text)
            else:
                self.last_final = utterance
                if utterance >= self.latest_draft:
                    self._draft("")
                if text:
                    self.enqueue(text, source="voice")
                else:
                    self._append("提示", "这句话没有识别清楚，未发送。请再说一次。", "notice")
        elif kind in {"too_long", "discard"}:
            # Capture can finish a later noise burst before ASR returns an earlier
            # real sentence. Do not invalidate that earlier final transcript.
            if payload >= self.latest_draft:
                self.latest_draft = payload
                self._draft("")
            if kind == "too_long":
                self._append("提示", "连续讲话超过 20 秒，本句未执行。请停顿后分句说。", "notice")
        elif kind == "error":
            self._append("提示", payload, "notice")
            self.stop_listening()

    def cancel(self):
        self.cancelled.set()
        self.pending.clear()
        self.stop_listening()
        self._append("提示", "已停止监听并清空队列。当前操作结束后不再执行后续动作。", "notice")

    def worker(self):
        import sys

        sys.coinit_flags = 0
        com = tools = None
        try:
            if sys.platform == "win32":
                import pythoncom

                com = pythoncom
                com.CoInitializeEx(com.COINIT_MULTITHREADED)
            tools = ToolRegistry(self.config, self.confirm)
            agent = Agent(
                self.config, JevClient(self.config), tools, self.log, self.confirm, self.cancelled
            )
            self.events.put(("ready", None))
            while True:
                job, value = self.jobs.get()
                if job == "exit":
                    break
                try:
                    if not self.closing.is_set():
                        agent.run(value[0], value[1])
                except Exception as error:
                    self.log(f"已停止：{type(error).__name__}: {error}")
                finally:
                    self.events.put(("idle", None))
        except Exception as error:
            self.events.put(("fatal", f"初始化失败：{error}"))
        finally:
            if tools:
                try:
                    tools.cleanup()
                except Exception as error:
                    self.log(f"浏览器退出清理失败：{error}")
            if com:
                com.CoUninitialize()
            self.events.put(("closed", None))

    def poll(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self._append("助手", payload)
                elif kind == "voice":
                    self.handle_voice(*payload)
                elif kind == "confirm":
                    text, done, answer = payload
                    if not self.closing.is_set() and not self.cancelled.is_set():
                        answer[0] = messagebox.askyesno("确认操作", text, parent=self.root)
                    done.set()
                elif kind == "ready":
                    self.worker_ready = True
                    self.status.set(
                        "就绪" if self.config.api_key else "请在 .env 配置 TYPESAFE_API_KEY 后重启"
                    )
                    self.refresh_controls()
                elif kind == "idle":
                    self.busy = False
                    if not self.closing.is_set():
                        self.status.set("就绪 · 可以继续说下一句")
                        self.dispatch()
                elif kind == "fatal":
                    self.worker_ready = False
                    self.stop_listening()
                    self.status.set(payload)
                    self._append("提示", payload, "notice")
                elif kind == "closed":
                    self.worker_ready = False
                    if self.closing.is_set():
                        self.root.destroy()
                        return
                    self.refresh_controls()
        except queue.Empty:
            pass
        self.root.after(60, self.poll)

    def close(self):
        if self.closing.is_set():
            return
        self.closing.set()
        self.cancelled.set()
        self.pending.clear()
        self.stop_listening()
        if not self.thread.is_alive():
            self.root.destroy()
            return
        self.status.set("正在退出，等待当前工具返回… 记事本将保留。")
        self.jobs.put(("exit", None))


def run():
    root = tk.Tk()
    try:
        App(root, Config.load())
    except Exception as error:
        messagebox.showerror("启动失败", str(error), parent=root)
        root.destroy()
        return
    root.mainloop()
