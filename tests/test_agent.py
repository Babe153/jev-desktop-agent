import io
import json
import threading
from unittest.mock import Mock
from urllib.error import HTTPError

import pytest

from desktop_agent.agent import Agent
from desktop_agent.config import Config
from desktop_agent.interpreter import arguments, split_steps
from desktop_agent.jev_client import Decision, JevClient
from desktop_agent.tools.files import FileTools


def test_quoted_steps_remain_literal():
    assert split_steps("打开记事本；然后写入：“先吃饭，然后散步；不要执行”；然后保存为：a.txt") == [
        "打开记事本",
        "写入：“先吃饭，然后散步；不要执行”",
        "保存为：a.txt",
    ]
    with pytest.raises(ValueError):
        split_steps("写入：“没有闭合")


def test_arguments_preserve_content_and_path():
    assert arguments("file_write", "写入文件：笔记.txt，内容：“你好，然后再见”") == {
        "path": "笔记.txt",
        "text": "你好，然后再见",
    }
    assert arguments("notepad_write", "写入：“你好，世界”") == {"text": "你好，世界"}
    assert arguments("browser_search", "搜索：Python 教程") == {"query": "Python 教程"}
    with pytest.raises(ValueError):
        arguments("file_write", "写入文件：笔记.txt")


def test_content_keyword_inside_literal_is_not_a_delimiter():
    assert arguments("notepad_write", "写入：“内容很好”") == {"text": "内容很好"}
    assert arguments("file_write", "写入文件：内容.txt，内容：“这里有内容二字”") == {
        "path": "内容.txt",
        "text": "这里有内容二字",
    }


def test_api_contract():
    body = {
        "answers": {
            "action": {
                "type": "choice",
                "choice": "open",
                "confidence": 0.9,
                "probabilities": {"open": 0.95, "unsupported": 0.05},
            }
        }
    }
    transport = Mock(return_value=io.BytesIO(json.dumps(body).encode()))
    client = JevClient(Config(api_key="test-key"), transport)
    result = client.choose({"current_instruction": "打开"}, {"open": "打开", "unsupported": "其他"})
    request = transport.call_args.args[0]
    assert request.full_url == "https://api.typesafe.ai/v1/systemone"
    assert request.get_header("Authorization") == "Bearer test-key"
    payload = json.loads(request.data)
    assert payload["model"] == "jev-latest"
    assert payload["questions"]["action"]["type"] == "choice"
    assert "criteria" in payload["questions"]["action"]
    assert result.choice == "open"


@pytest.mark.parametrize(
    "answer",
    [
        {"type": "choice", "choice": "shell", "confidence": 1, "probabilities": {"open": 1}},
        {
            "type": "choice",
            "choice": "open",
            "confidence": float("nan"),
            "probabilities": {"open": 1},
        },
        {"type": "choice", "choice": "open", "confidence": 1, "probabilities": {"open": 0.1}},
    ],
)
def test_api_rejects_invalid_answers(answer):
    transport = Mock(return_value=io.BytesIO(json.dumps({"answers": {"action": answer}}).encode()))
    with pytest.raises(RuntimeError):
        JevClient(Config(api_key="x"), transport).choose({}, {"open": "打开"})


def test_no_key_means_no_request():
    transport = Mock()
    with pytest.raises(ValueError, match="TYPESAFE_API_KEY"):
        JevClient(Config(api_key=""), transport).choose({}, {"open": "打开"})
    transport.assert_not_called()


def test_http_error_does_not_leak_body_or_key():
    transport = Mock(side_effect=HTTPError("https://api.typesafe.ai", 401, "secret", {}, None))
    with pytest.raises(RuntimeError, match="401") as error:
        JevClient(Config(api_key="secret"), transport).choose({}, {"open": "打开"})
    assert "secret" not in str(error.value)


def test_file_scope_and_overwrite(tmp_path):
    confirm = Mock(return_value=False)
    files = FileTools(tmp_path, confirm)
    for name in ["../escape.txt", "C:\\outside.txt", "bad.exe", "bad?.txt"]:
        with pytest.raises(ValueError):
            files.resolve(name)
    files.write("中文.txt", "第一行")
    with pytest.raises(RuntimeError):
        files.write("中文.txt", "替换")
    assert files.read("中文.txt") == "第一行"
    files.write("中文.txt", "\n第二行", append=True)
    assert files.read("中文.txt") == "第一行\n第二行"
    with pytest.raises(FileExistsError):
        files.write("中文.txt", "", exclusive=True)


def make_agent(decisions, execute=None):
    client, tools = Mock(), Mock()
    client.choose.side_effect = decisions
    tools.observe.return_value = {}
    tools.execute.side_effect = execute
    cancel = threading.Event()
    agent = Agent(Config(api_key="x"), client, tools, Mock(), Mock(return_value=False), cancel)
    return agent, tools, cancel


def test_failure_stops_later_actions():
    agent, tools, _ = make_agent([Decision("notepad_open", 1, {})], RuntimeError("failed"))
    with pytest.raises(RuntimeError):
        agent.run("打开记事本；然后搜索：猫")
    assert tools.execute.call_count == 1
    assert agent.client.choose.call_count == 1


def test_preview_calls_jev_without_execution():
    agent, tools, _ = make_agent([Decision("browser_search", 1, {})])
    agent.run("搜索：猫", dry_run=True)
    agent.client.choose.assert_called_once()
    tools.execute.assert_not_called()


def test_low_confidence_requires_confirmation():
    agent, tools, _ = make_agent([Decision("browser_search", 0.2, {})])
    with pytest.raises(RuntimeError):
        agent.run("搜索：猫")
    agent.confirm.assert_called_once()
    tools.execute.assert_not_called()


def test_cancel_during_request_stops_execution():
    agent, tools, cancel = make_agent([])

    def choose(*args):
        cancel.set()
        return Decision("browser_search", 1, {})

    agent.client.choose.side_effect = choose
    agent.run("搜索：猫")
    tools.execute.assert_not_called()
