"""Local, persistent browser session. Login is performed by the user, never by AI."""
import concurrent.futures
import io
import queue
import sys
import threading
from pathlib import Path
from urllib.request import Request, build_opener
from urllib.parse import urlparse, urljoin
import beta

RUNTIME = Path(__file__).resolve().parent / "work/runtime-packages"
if RUNTIME.is_dir(): sys.path.insert(0, str(RUNTIME))


def public_read(url):
    result = {"url": url, "status": "unavailable"}
    try:
        beta.public_url(url)
        with build_opener(beta.PublicRedirect()).open(Request(url, headers={"User-Agent": "UWMaster/1.0Beta"}), timeout=15) as response:
            mime, final_url = response.headers.get_content_type(), response.url
            raw = response.read(8 * 1024 * 1024 + 1)
            encoding = response.headers.get_content_charset() or "utf-8"
        if len(raw) > 8 * 1024 * 1024: raise ValueError("来源超过 8 MB 读取限制")
        if mime == "application/pdf":
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw))
            extracted = "\n".join(page.extract_text() or "" for page in reader.pages[:80])
            truncated = len(reader.pages) > 80 or len(extracted) > 100000
            text = extracted[:100000]
            if len(text.strip()) < 100: return {**result, "message": "PDF 缺少可提取文字，需要单独核查。"}
            return {"url": url, "final_url": final_url, "status": "read", "text": text, "truncated": truncated, "message": "已读取 PDF 文字（达到内容上限，部分读取）。" if truncated else "已读取 PDF 文字。", "links": []}
        if mime not in {"text/html", "text/plain"}:
            return {**result, "message": "该来源类型不支持，需要单独核查。"}
        html = raw.decode(encoding, errors="replace")
        if any(word in final_url.lower() for word in ("/login", "/signin", "/saml", "/sso")) or 'type="password"' in html.lower() or "type='password'" in html.lower():
            return {**result, "status": "login_required", "message": "需要登录后核查。"}
        class LinkedText(beta.PageText):
            def __init__(self):
                super().__init__()
                self.links = []
            def handle_starttag(self, tag, attrs):
                super().handle_starttag(tag, attrs)
                href = dict(attrs).get("href")
                if tag == "a" and href:
                    self.links.append({"url": urljoin(final_url, href), "title": ""})
        parser = LinkedText()
        parser.feed(html)
        extracted = "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())
        text = extracted[:100000]
        if len(text) < 100: return {**result, "message": "未读到完整文字，可能需要浏览器登录或页面脚本。"}
        return {"url": url, "final_url": final_url, "status": "read", "text": text, "truncated": len(extracted) > 100000, "links": parser.links[:500], "message": "已读取公开页面文字（达到内容上限，部分读取）。" if len(extracted) > 100000 else "已读取公开页面文字。"}
    except ImportError:
        return {**result, "message": "PDF 读取依赖未安装，请运行 setup_retrieval.ps1。"}
    except Exception:
        return {**result, "message": "来源读取失败，需要浏览器或单独核查。"}


class BrowserCollector:
    def __init__(self):
        self.commands = queue.Queue()
        self.lock = threading.Lock()
        self.state = {"status": "disconnected", "message": "尚未连接课程浏览器。"}
        self.worker = None

    def status(self):
        with self.lock: return dict(self.state)

    def set_state(self, status, message):
        with self.lock: self.state = {"status": status, "message": message}

    def submit(self, action, url=None):
        with self.lock:
            if self.worker is None or not self.worker.is_alive():
                self.worker = threading.Thread(target=self.run, daemon=True)
                self.worker.start()
        future = concurrent.futures.Future()
        self.commands.put((action, url, future))
        return future

    def connect(self, url):
        beta.public_url(url)
        self.set_state("connecting", "正在打开专用浏览器，请自行登录课程平台。")
        self.submit("connect", url)
        return self.status()

    def read(self, url):
        if self.status()["status"] != "connected":
            return {"url": url, "status": "login_required", "message": "请先连接课程浏览器并自行登录。"}
        try: return self.submit("read", url).result(timeout=50)
        except Exception: return {"url": url, "status": "unavailable", "message": "浏览器读取失败或超时，请检查登录状态。"}

    def disconnect(self):
        self.submit("disconnect")
        return {"status": "disconnecting", "message": "正在关闭课程浏览器；会话保留在本机。"}

    def run(self):
        context = manager = playwright = None
        while True:
            try:
                action, url, future = self.commands.get(timeout=.1)
            except queue.Empty:
                # Pump Playwright events while the user performs login in the browser.
                if context:
                    try:
                        pages = context.pages
                        if pages: pages[0].wait_for_timeout(100)
                    except Exception:
                        context = None
                        if manager:
                            try: manager.stop()
                            except Exception: pass
                        manager = None
                        self.set_state("disconnected", "课程浏览器已关闭，请重新连接。")
                continue
            try:
                if action == "disconnect":
                    if context: context.close()
                    if manager: manager.stop()
                    context = manager = None
                    self.set_state("disconnected", "课程浏览器已关闭。")
                    future.set_result(self.status())
                    continue
                if not context:
                    from playwright.sync_api import sync_playwright
                    manager = sync_playwright().start()
                    profile = Path(__file__).resolve().parent / "data/course-browser"
                    profile.mkdir(parents=True, exist_ok=True)
                    context = manager.chromium.launch_persistent_context(str(profile), channel="msedge", headless=False,
                                                                        accept_downloads=False)
                    def filter_request(route):
                        try:
                            if route.request.url.startswith(("data:", "blob:")): return route.continue_()
                            beta.public_url(route.request.url)
                            route.continue_()
                        except Exception: route.abort()
                    context.route("**/*", filter_request)
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                if action == "connect":
                    self.set_state("connected", "课程浏览器已打开。请自行完成登录；是否有权读取将在检索时核实。")
                    future.set_result(self.status())
                    continue
                page.wait_for_timeout(1200)
                extracted = page.locator("body").inner_text(timeout=10000)
                text = extracted[:100000]
                final = page.url
                login = any(word in final.lower() for word in ("/login", "/signin", "/saml", "/sso")) or page.locator('input[type="password"]').count()
                links = page.locator("a[href]").evaluate_all("nodes => nodes.map(n => ({url:n.href,title:n.innerText})).slice(0,500)")
                result = {"url": url, "final_url": final, "status": "login_required" if login else "read" if len(text.strip()) >= 100 else "unavailable",
                          "message": "登录尚未完成或已过期。" if login else "已读取浏览器页面；浏览可能触发平台的阅读标记，不能据此推断整项完成。",
                          "text": "" if login else text, "links": [] if login else links, "truncated": len(extracted) > 100000}
                if result["truncated"]: result["message"] += "已达到内容上限，本次为部分读取。"
                page.close()
                self.set_state("connected", "课程浏览器可用；各平台登录状态在读取时核实。")
                future.set_result(result)
            except Exception:
                context = None
                if manager:
                    try: manager.stop()
                    except Exception: pass
                manager = None
                self.set_state("unavailable", "课程浏览器不可用，请运行 setup_retrieval.ps1，或检查 Edge 与登录窗口。")
                future.set_result({"url": url, "status": "unavailable", "message": self.status()["message"]})


BROWSER = BrowserCollector()
