from urllib.parse import urlencode, urlparse


class BrowserTools:
    """One dedicated, visible browser; never closes the user's other browsers."""

    def __init__(self):
        self.driver = self.browser = self.page = None
        self.browser_name = None

    @property
    def active(self):
        return self.browser is not None and self.browser.is_connected()

    def open(self, url):
        if urlparse(url).scheme not in {"http", "https"} or not urlparse(url).hostname:
            raise ValueError("浏览器只接受 http/https 地址。")
        if not self.active:
            from playwright.sync_api import Error, sync_playwright

            if self.driver:
                self.driver.stop()
            self.browser = self.page = None
            self.driver = sync_playwright().start()
            failures = []
            # A bundled executable may be present yet fail to spawn on Windows.
            # Installed channels still use a separate, temporary browser profile.
            for channel, label in ((None, "Chromium"), ("msedge", "Edge"), ("chrome", "Chrome")):
                options = {"headless": False}
                if channel:
                    options["channel"] = channel
                try:
                    self.browser = self.driver.chromium.launch(**options)
                    self.browser_name = label
                    break
                except Error as error:
                    failures.append(f"{label}: {str(error).splitlines()[0]}")
            if self.browser is None:
                self.driver.stop()
                self.driver = None
                raise RuntimeError(
                    "浏览器启动失败。已尝试 Chromium、Edge、Chrome。"
                    "请安装 Edge/Chrome，或运行 uv run playwright install chromium。\n"
                    + "\n".join(failures)
                )
        if self.page is None or self.page.is_closed():
            self.page = self.browser.new_page()
        self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
        self.page.bring_to_front()
        return f"浏览器已打开（{self.browser_name or 'Chromium'}）：{self.page.url}"

    def search(self, query):
        return self.open("https://www.bing.com/search?" + urlencode({"q": query}))

    def close(self):
        if self.browser and self.browser.is_connected():
            self.browser.close()
        if self.driver:
            self.driver.stop()
        self.driver = self.browser = self.page = None
        self.browser_name = None
        return "助手浏览器已关闭。"
