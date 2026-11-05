"""One helper owns Playwright's sync API, including on Windows selector loops.

Operations have finite timeouts. Cancellation fences the next operation; an
already submitted click cannot be rolled back. No shared personal browser profile.
"""

import threading
import json
from pathlib import Path

from services.browser.models import Observation, Step
from services.browser.safety import MAX_HTML_BYTES, download_file, extract_html, public_url
from services.browser.worker import ProcessRuntime


class BrowserControls:
    def __init__(self, stopped: threading.Event, downloads: Path):
        self.stopped, self.downloads = stopped, downloads
        self.playwright = self.browser = self.context = self.page = None
        self.handles = {}
        self.read_only = True
        self.downloading = False
        self.last_observation = None

    def _check(self):
        if self.stopped.is_set():
            raise InterruptedError("Task stopped")

    def start(self, headless: bool):
        self._check()
        from playwright.sync_api import sync_playwright
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=headless)
        self.context = self.browser.new_context(viewport={"width": 1280, "height": 900},
                                                accept_downloads=True, service_workers="block")
        self.context.set_default_timeout(8000)
        self.context.set_default_navigation_timeout(15000)
        self.context.route("**/*", self._route)
        self.context.route_web_socket("**/*", lambda ws: ws.close())
        self.context.on("page", self._page_opened)
        self.page = self.context.new_page()
        return self.observe()

    def _route(self, route):
        try:
            self._check()
            request = route.request
            # Check every destination, including subresources and redirects. The
            # DNS check is not a network sandbox; contexts have no owner cookies.
            public_url(request.url)
            if self.read_only and request.method not in {"GET", "HEAD"}:
                raise ValueError("Research cannot submit forms")
            route.continue_()
        except Exception:
            route.abort()

    def _page_opened(self, page):
        # Same-context popup tabs are observed next. No connection to the user's
        # ordinary Chrome session, and no extra automation task starts here.
        page.on("dialog", lambda dialog: dialog.dismiss())
        page.on("download", self._unexpected_download)

    def _unexpected_download(self, download):
        if not self.downloading:
            download.cancel()

    def _current_page(self):
        pages = [p for p in self.context.pages if not p.is_closed()]
        if not pages:
            raise ValueError("The browser window was closed")
        self.page = pages[-1]
        return self.page

    def observe(self, dispose=True):
        self._check()
        page = self._current_page()
        if dispose:
            for handle in self.handles.values():
                handle.dispose()
        self.handles = {}
        controls = []
        control_chars = 0
        for element in page.query_selector_all("a[href],button,input,textarea,select,[role=button],[role=link]")[:250]:
            if len(controls) >= 80:
                element.dispose()
                continue
            if not element.is_visible():
                element.dispose()
                continue
            data = element.evaluate("""e => ({kind:e.tagName.toLowerCase(),
                name:(e.getAttribute('aria-label') || e.labels?.[0]?.innerText ||
                      e.getAttribute('placeholder') || e.innerText || e.name || e.type || '').slice(0,180),
                type:e.getAttribute('type') || '', href:e.tagName==='A' ? e.href.slice(0,1000) : '',
                value:['INPUT','TEXTAREA','SELECT'].includes(e.tagName) && e.type!=='password' ? e.value.slice(0,1000) : '',
                disabled:!!e.disabled, protected:e.type==='password' ||
                  /password|credit.card|cc-number|cc-csc|one-time-code/.test(e.autocomplete || '')})""")
            if data["protected"] or data["disabled"]:
                element.dispose()
                continue
            control_chars += len(json.dumps(data, ensure_ascii=False))
            if control_chars > 12000:
                element.dispose()
                continue
            data["id"] = len(controls) + 1
            self.handles[data["id"]] = element
            controls.append(data)
        text = page.locator("body").inner_text(timeout=4000)[:12000] if page.url != "about:blank" else "Blank browser tab."
        observation = Observation(page.url, page.title()[:300], text, controls)
        self.last_observation = observation
        return observation

    def read(self, url: str):
        self._check()
        url = public_url(url)
        response = self.page.goto(url, wait_until="domcontentloaded")
        if not response or response.status >= 400:
            raise ValueError("Page fetch failed")
        if int(response.headers.get("content-length", "0")) > MAX_HTML_BYTES:
            raise ValueError("Page exceeds the extraction limit")
        self.page.wait_for_timeout(400)
        self._check()
        final_url = public_url(self.page.url)
        html = self.page.content()
        title, text = extract_html(html, final_url)
        # Rendered visibility wins over static markup on browser-loaded pages.
        main = self.page.locator("main, article, [role=main]").first
        visible = " ".join((main if main.count() and main.is_visible() else self.page.locator("body"))
                           .inner_text(timeout=4000).split())[:12000]
        if len(visible) < 1200 and any(s in visible.lower() for s in
                ("access denied", "checking your browser", "verify you are human", "captcha")):
            raise ValueError("Page requires owner help or access verification")
        return final_url, title, visible or text

    def execute(self, step: Step, fingerprint: str):
        self._check()
        previous = self.handles
        try:
            observed = self.observe(dispose=False)
            old, current = previous.get(step.target), self.handles.get(step.target)
            same_node = not step.target or (old and current and old.evaluate("(e,other) => e === other", current))
            if observed.fingerprint() != fingerprint or not same_node:
                raise ValueError("The page changed; review a fresh step")
        finally:
            for handle in previous.values():
                handle.dispose()
        self._check()
        self.read_only = False  # only during the individually approved operation
        receipt = ""
        try:
            if step.action == "navigate":
                url = public_url(step.value)
                self._check()
                response = self.page.goto(url, wait_until="domcontentloaded")
                if response and response.status >= 400:
                    raise ValueError("Navigation returned an error")
                public_url(self.page.url)
                receipt = f"Navigation reached {self.page.url}"
            else:
                target = self.handles.get(step.target)
                if not target or not target.is_visible() or not target.is_enabled():
                    raise ValueError("The target is no longer available")
                if target.get_attribute("type") == "password":
                    raise ValueError("Protected input")
                self._check()
                if step.action == "fill":
                    target.fill(step.value)
                    if target.input_value() != step.value:
                        raise ValueError("Text entry did not match")
                    receipt = "Entered text; field value verified."
                elif step.action == "press":
                    target.press(step.value)
                    receipt = "Key submitted; inspect the resulting page state."
                elif step.action == "download":
                    receipt = self._download(target)
                elif step.action == "click":
                    target.click()
                    receipt = "Click submitted; inspect the resulting page state."
                else:
                    raise ValueError("Unsupported browser operation")
            self._check()
            self.page.wait_for_timeout(200)
            return receipt, self.observe()
        finally:
            self.read_only = True

    def _download(self, target):
        href = target.evaluate("e => e.tagName === 'A' ? e.href : ''")
        if not href:
            raise ValueError("Use a direct public download link; authenticated/button downloads need owner help")
        path, size, digest = download_file(href, self.downloads, self.stopped)
        return f"Downloaded {path.name} ({size} bytes), SHA-256 {digest}, saved at {path}. File was not opened."

    def close(self):
        try:
            if self.browser:
                self.browser.close()
        finally:
            if self.playwright:
                self.playwright.stop()
            self.handles = {}


class BrowserRuntime(ProcessRuntime):
    def __init__(self, stopped, downloads):
        self.downloads = downloads
        super().__init__(BrowserControls, (downloads,), stopped, browser_tree=True, timeout=35)

    async def aclose(self):
        try:
            await super().aclose()
        finally:
            # Only partial files in this task's unique owned download directory.
            for partial in self.downloads.glob("*.part"):
                partial.unlink(missing_ok=True)
