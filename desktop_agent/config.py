import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    api_key: str
    model: str = "jev-latest"
    timeout: float = 30
    min_confidence: float = 0.5
    workspace: Path = ROOT / "data" / "workspace"
    whisper_model: str = "small"
    language: str = "zh"
    mic_device: int | None = None
    camera_roll_dir: Path | None = None
    speech_silence: float = 1.0
    speech_threshold: float = 0.012
    speech_partial_interval: float = 1.0

    @classmethod
    def load(cls):
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env", override=False)
        folder = Path(os.getenv("WORKSPACE_DIR", "data/workspace"))
        confidence = float(os.getenv("JEV_MIN_CONFIDENCE", "0.5"))
        if not 0 <= confidence <= 1:
            raise ValueError("JEV_MIN_CONFIDENCE 必须在 0 到 1 之间")
        timeout = float(os.getenv("JEV_TIMEOUT_SECONDS", "30"))
        if not 1 <= timeout <= 120:
            raise ValueError("JEV_TIMEOUT_SECONDS 必须在 1 到 120 之间")
        mic = os.getenv("MIC_DEVICE", "").strip()
        roll = os.getenv("CAMERA_ROLL_DIR", "").strip()
        silence = float(os.getenv("SPEECH_SILENCE_SECONDS", "1.0"))
        threshold = float(os.getenv("SPEECH_RMS_THRESHOLD", "0.012"))
        interval = float(os.getenv("SPEECH_PARTIAL_INTERVAL", "1.0"))
        if not 0.4 <= silence <= 4 or not 0.001 <= threshold <= 0.2 or not 0.5 <= interval <= 5:
            raise ValueError("语音配置范围：停顿 0.4–4 秒，阈值 0.001–0.2，刷新 0.5–5 秒。")
        return cls(
            api_key=os.getenv("TYPESAFE_API_KEY", "").strip(),
            model=os.getenv("JEV_MODEL", "jev-latest"),
            timeout=timeout,
            min_confidence=confidence,
            workspace=(folder if folder.is_absolute() else ROOT / folder).resolve(),
            whisper_model=os.getenv("WHISPER_MODEL", "small"),
            language=os.getenv("WHISPER_LANGUAGE", "zh"),
            mic_device=int(mic) if mic else None,
            camera_roll_dir=Path(os.path.expandvars(roll)).expanduser().resolve() if roll else None,
            speech_silence=silence,
            speech_threshold=threshold,
            speech_partial_interval=interval,
        )
