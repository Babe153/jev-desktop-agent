from unittest.mock import Mock, patch

import pytest
from playwright.sync_api import Error

from desktop_agent.tools.browser import BrowserTools


def test_visible_browser_falls_back_to_edge_when_chromium_cannot_spawn():
    driver, browser, page = Mock(), Mock(), Mock()
    driver.chromium.launch.side_effect = [Error("spawn UNKNOWN"), browser]
    browser.new_page.return_value = page
    page.url = "https://example.com"
    with patch("playwright.sync_api.sync_playwright") as factory:
        factory.return_value.start.return_value = driver
        tools = BrowserTools()
        result = tools.open("https://example.com")
    assert driver.chromium.launch.call_args_list[0].kwargs == {"headless": False}
    assert driver.chromium.launch.call_args_list[1].kwargs == {
        "headless": False,
        "channel": "msedge",
    }
    assert "Edge" in result
    page.goto.assert_called_once()
    tools.close()
    browser.close.assert_called_once()
    driver.stop.assert_called_once()


def test_all_launch_failures_cleanup_and_allow_retry():
    driver = Mock()
    driver.chromium.launch.side_effect = Error("spawn UNKNOWN")
    with patch("playwright.sync_api.sync_playwright") as factory:
        factory.return_value.start.return_value = driver
        tools = BrowserTools()
        with pytest.raises(RuntimeError, match="浏览器启动失败"):
            tools.open("https://example.com")
    assert driver.chromium.launch.call_count == 3
    driver.stop.assert_called_once()
    assert tools.driver is None
    assert tools.browser is None


def test_reopen_drops_page_from_disconnected_browser():
    tools = BrowserTools()
    old_driver, old_browser, old_page = Mock(), Mock(), Mock()
    old_browser.is_connected.return_value = False
    old_page.is_closed.return_value = False
    tools.driver, tools.browser, tools.page = old_driver, old_browser, old_page
    driver, browser = Mock(), Mock()
    driver.chromium.launch.return_value = browser
    with patch("playwright.sync_api.sync_playwright") as factory:
        factory.return_value.start.return_value = driver
        tools.open("https://example.com")
    old_driver.stop.assert_called_once()
    old_page.goto.assert_not_called()
    browser.new_page.assert_called_once()
