"""Bounded, local incremental transcription. Only final utterances become commands."""

import queue
import threading
from collections import deque
from dataclasses import dataclass

import numpy as np


@dataclass
class AudioUpdate:
    utterance: int
    kind: str
    audio: np.ndarray | None = None


class Segmenter:
    """Energy gate with preroll, silence endpoint and a hard utterance duration limit."""

    def __init__(
        self, rate=16000, threshold=0.012, silence=1.0, partial_interval=1.0, max_duration=20
    ):
        self.rate, self.threshold = rate, threshold
        self.silence = silence
        self.partial_interval = partial_interval
        self.max_duration = max_duration
        self.preroll = deque(maxlen=5)  # 250 ms at our 50 ms callback size.
        self.utterance = 0
        self.frames = []
        self.duration = self.voiced = self.quiet = self.since_partial = 0.0
        self.dropping = False

    def feed(self, block):
        duration = len(block) / self.rate
        loud = float(np.sqrt(np.mean(np.square(block)))) >= self.threshold
        if self.dropping:
            self.quiet = 0 if loud else self.quiet + duration
            if self.quiet >= self.silence:
                self.dropping = False
                self.quiet = 0
            return []
        if not self.frames:
            if not loud:
                self.preroll.append(block)
                return []
            self.utterance += 1
            self.frames = list(self.preroll)
            self.preroll.clear()
            self.duration = self.voiced = self.quiet = self.since_partial = 0.0
        self.frames.append(block)
        self.duration += duration
        self.since_partial += duration
        self.voiced += duration if loud else 0
        self.quiet = 0 if loud else self.quiet + duration
        if self.duration >= self.max_duration:
            self.frames = []
            self.dropping = True
            self.quiet = 0
            return [AudioUpdate(self.utterance, "too_long")]
        if self.quiet + 1e-6 >= self.silence:
            audio = np.concatenate(self.frames)
            self.frames = []
            if self.voiced < 0.3:
                return [AudioUpdate(self.utterance, "discard")]
            return [AudioUpdate(self.utterance, "final", audio)]
        if self.since_partial >= self.partial_interval and self.voiced >= 0.3:
            self.since_partial = 0
            return [AudioUpdate(self.utterance, "partial", np.concatenate(self.frames))]
        return []


class SpeechMailbox:
    """Coalesce interim audio; prioritize finals and bound backlog."""

    def __init__(self):
        self.condition = threading.Condition()
        self.finals = deque()
        self.partial = None
        self.closed = False
        self.finished = 0

    def put(self, update):
        with self.condition:
            if self.closed or update.utterance <= self.finished:
                return
            if update.kind == "partial":
                self.partial = update
            else:
                self.finished = update.utterance
                if self.partial and self.partial.utterance <= self.finished:
                    self.partial = None
                if update.kind == "final":
                    if len(self.finals) >= 3:
                        raise RuntimeError(
                            "语音识别跟不上说话速度，已停止监听。请稍慢说或使用更小的模型。"
                        )
                    self.finals.append(update)
            self.condition.notify()

    def get(self):
        with self.condition:
            self.condition.wait_for(lambda: self.closed or self.finals or self.partial is not None)
            if self.closed:
                return None
            if self.finals:
                return self.finals.popleft()
            result, self.partial = self.partial, None
            return result

    def close(self):
        with self.condition:
            self.closed = True
            self.finals.clear()
            self.partial = None
            self.condition.notify_all()


class ContinuousListener:
    def __init__(self, config, transcriber, emit):
        self.config, self.transcriber, self.emit = config, transcriber, emit
        self.stopped = threading.Event()
        self.audio = queue.Queue(maxsize=200)  # At most ten seconds of raw capture.
        self.mailbox = SpeechMailbox()
        self.thread = None
        self.problem = None

    def start(self):
        self.thread = threading.Thread(target=self._run, name="voice-capture", daemon=True)
        self.thread.start()

    def stop(self):
        self.stopped.set()
        self.mailbox.close()  # Discard incomplete utterances and pending recognitions.

    def _send(self, kind, payload=None):
        if not self.stopped.is_set():
            self.emit(kind, payload)

    def _recognize(self):
        try:
            while not self.stopped.is_set():
                update = self.mailbox.get()
                if update is None:
                    return
                text = self.transcriber.transcribe(
                    update.audio,
                    partial=update.kind == "partial",
                    allow_empty=True,
                )
                # A slow partial must not replace an already finalized utterance.
                if update.kind == "partial" and update.utterance <= self.mailbox.finished:
                    continue
                self._send(update.kind, (update.utterance, text))
        except Exception as error:
            self._send("error", f"语音识别失败：{error}")
            self.stop()

    def _run(self):
        try:
            self._send("loading", "正在加载本地语音模型，首次使用可能需要下载…")
            self.transcriber.prepare()
            if self.stopped.is_set():
                return
            import sounddevice as sd

            segmenter = Segmenter(
                threshold=self.config.speech_threshold,
                silence=self.config.speech_silence,
                partial_interval=self.config.speech_partial_interval,
            )

            def capture(data, frames, timing, status):
                if status:
                    self.problem = f"录音设备报告错误：{status}"
                    return
                try:
                    self.audio.put_nowait(data[:, 0].copy())
                except queue.Full:
                    self.problem = "音频缓冲区已满，已停止监听，请重试。"

            with sd.InputStream(
                samplerate=16000,
                blocksize=800,
                channels=1,
                dtype="float32",
                device=self.config.mic_device,
                callback=capture,
            ):
                threading.Thread(
                    target=self._recognize, name="voice-recognition", daemon=True
                ).start()
                self._send("ready")
                while not self.stopped.is_set():
                    if self.problem:
                        raise RuntimeError(self.problem)
                    try:
                        block = self.audio.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    for update in segmenter.feed(block):
                        self.mailbox.put(update)
                        if update.kind in {"too_long", "discard"}:
                            self._send(update.kind, update.utterance)
        except Exception as error:
            self._send("error", str(error))
        finally:
            self.stop()
