import tkinter as tk
from unittest.mock import patch

import pytest

from desktop_agent.config import Config
from desktop_agent.gui import App


@pytest.mark.parametrize("size", ["920x780", "760x620"])
def test_input_and_buttons_stay_inside_window(size):
    root = tk.Tk()
    try:
        # Test actual widget geometry without tools, microphone or network activity.
        with patch.object(App, "worker", lambda self: None):
            app = App(root, Config(api_key=""))
        root.geometry(size)
        root.update()
        for widget in (app.record_button, app.run_button, app.input):
            assert widget.winfo_ismapped()
            x = widget.winfo_rootx() - root.winfo_rootx()
            y = widget.winfo_rooty() - root.winfo_rooty()
            assert 0 <= x < root.winfo_width()
            assert 0 <= y < root.winfo_height()
            assert x + widget.winfo_width() <= root.winfo_width()
            assert y + widget.winfo_height() <= root.winfo_height()
        assert app.record_button.cget("text") == "开始对话"
        assert app.run_button.cget("text") == "发送文字"
    finally:
        root.destroy()
