import queue
import threading
from collections import deque
from unittest.mock import Mock

import numpy as np
import pytest

from desktop_agent.config import Config
from desktop_agent.continuous import AudioUpdate, ContinuousListener, Segmenter, SpeechMailbox
from desktop_agent.gui import App


def feed(segmenter, seconds, loud=True):
    updates = []
    block = np.full(800, 0.1 if loud else 0, dtype=np.float32)
    for _ in range(round(seconds / 0.05)):
        updates.extend(segmenter.feed(block))
    return updates


def test_continuous_speech_has_partials_and_exactly_one_final_after_pause():
    s = Segmenter()
    assert feed(s, 2, loud=False) == []
    speaking = feed(s, 2)
    assert any(update.kind == "partial" for update in speaking)
    assert not any(update.kind == "final" for update in speaking)
    ending = feed(s, 1.2, loud=False)
    finals = [update for update in ending if update.kind == "final"]
    assert len(finals) == 1 and finals[0].utterance == 1
    assert feed(s, 2, loud=False) == []
    feed(s, 0.5)
    ending = feed(s, 1.2, loud=False)
    assert [u.utterance for u in ending if u.kind == "final"] == [2]


def test_short_noise_and_overlong_speech_never_execute():
    s = Segmenter(max_duration=3)
    feed(s, 0.1)
    ending = feed(s, 1.2, loud=False)
    assert [u.kind for u in ending] == ["discard"]
    updates = feed(s, 5)
    assert len([u for u in updates if u.kind == "too_long"]) == 1
    assert not any(u.kind == "final" for u in updates)
    assert feed(s, 1.2, loud=False) == []
    feed(s, 0.5)
    assert any(u.kind == "final" for u in feed(s, 1.2, loud=False))


def test_mailbox_coalesces_partials_and_prioritizes_final():
    box = SpeechMailbox()
    box.put(AudioUpdate(1, "partial", np.array([1])))
    box.put(AudioUpdate(1, "partial", np.array([2])))
    assert box.get().audio[0] == 2
    box.put(AudioUpdate(1, "partial"))
    box.put(AudioUpdate(1, "final"))
    box.put(AudioUpdate(2, "partial"))
    assert box.get().kind == "final"
    assert box.get().utterance == 2
    box.close()
    assert box.get() is None


def test_backlog_is_bounded():
    box = SpeechMailbox()
    for i in range(1, 4):
        box.put(AudioUpdate(i, "final"))
    with pytest.raises(RuntimeError, match="跟不上"):
        box.put(AudioUpdate(4, "final"))


def app_stub():
    app = App.__new__(App)
    app.config = Config(api_key="test")
    app.session = 1
    app.listener = Mock()
    app.last_final = app.latest_draft = 0
    app.closing, app.cancelled = threading.Event(), threading.Event()
    app.busy = False
    app.worker_ready = True
    app.pending = deque()
    app.jobs = queue.Queue()
    app.preview = Mock()
    app.preview.get.return_value = False
    app.status, app.voice_status = Mock(), Mock()
    app._draft, app._append, app.refresh_controls = Mock(), Mock(), Mock()
    return app


def test_interim_never_executes_and_final_auto_dispatches_only_once():
    app = app_stub()
    app.handle_voice(1, "partial", (1, "打开浏"))
    assert app.jobs.empty()
    app._draft.assert_called_with("打开浏")
    app.handle_voice(1, "final", (1, "打开浏览器"))
    assert app.jobs.get_nowait() == ("execute", ("打开浏览器", False))
    app.handle_voice(1, "final", (1, "打开浏览器"))
    app.handle_voice(1, "partial", (1, "过时的识别"))
    assert app.jobs.empty()


def test_execution_does_not_block_next_utterance_and_stop_drops_queue():
    app = app_stub()
    app.handle_voice(1, "final", (1, "打开浏览器"))
    app.handle_voice(1, "final", (2, "搜索 Python"))
    assert len(app.pending) == 1
    app.stop_listening()
    assert len(app.pending) == 0
    app.handle_voice(1, "final", (3, "不应发送"))
    assert app.jobs.qsize() == 1


def test_noise_after_valid_audio_does_not_discard_delayed_final():
    app = app_stub()
    app.handle_voice(1, "discard", 2)
    app.handle_voice(1, "final", (1, "打开浏览器"))
    assert app.jobs.get_nowait() == ("execute", ("打开浏览器", False))


def test_empty_final_and_old_session_do_not_execute():
    app = app_stub()
    app.handle_voice(0, "final", (1, "打开浏览器"))
    app.handle_voice(1, "final", (1, ""))
    assert app.jobs.empty()


def test_recognition_failure_stops_listener():
    transcriber, emit = Mock(), Mock()
    transcriber.transcribe.side_effect = RuntimeError("test failure")
    listener = ContinuousListener(Config(api_key=""), transcriber, emit)
    listener.mailbox.put(AudioUpdate(1, "final", np.zeros(800)))
    listener._recognize()
    assert listener.stopped.is_set()
    assert emit.call_args.args[0] == "error"


def test_stop_during_inference_suppresses_late_final():
    transcriber, emit = Mock(), Mock()
    listener = ContinuousListener(Config(api_key=""), transcriber, emit)

    def recognize(*args, **kwargs):
        listener.stop()
        return "不要执行"

    transcriber.transcribe.side_effect = recognize
    listener.mailbox.put(AudioUpdate(1, "final", np.zeros(800)))
    listener._recognize()
    emit.assert_not_called()
