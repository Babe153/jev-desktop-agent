import threading


class Transcriber:
    def __init__(self, config):
        self.config = config
        self.model = None
        self.lock = threading.Lock()

    def prepare(self):
        from faster_whisper import WhisperModel

        with self.lock:
            if self.model is None:
                self.model = WhisperModel(
                    self.config.whisper_model, device="cpu", compute_type="int8"
                )

    def transcribe(self, audio, partial=False, allow_empty=False):
        self.prepare()
        with self.lock:
            segments, _ = self.model.transcribe(
                audio,
                language=self.config.language or None,
                vad_filter=True,
                beam_size=1 if partial else 3,
                condition_on_previous_text=False,
            )
            text = "".join(segment.text for segment in segments).strip()
        if not text and not allow_empty:
            raise ValueError("没有识别到文字，请重新录音。")
        return text
