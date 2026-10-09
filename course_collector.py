"""Persistent browser session; credentials stay in the browser's login form."""
import concurrent.futures
import io
import queue
import re
import sys
import threading
from pathlib import Path
from urllib.request import Request, build_opener
from urllib.parse import urlparse, urljoin
import beta

RUNTIME = Path(__file__).resolve().parent / "work/runtime-packages"
if RUNTIME.is_dir(): sys.path.insert(0, str(RUNTIME))

UW_LOGIN_HOSTS = {'canvas.uw.edu', 'idp.u.washington.edu', 'weblogin.washington.edu'}


def needs_login(page):
    host = urlparse(page.url).hostname or ''
    return (any(word in page.url.lower() for word in ('/login', '/signin', '/saml', '/sso'))
            or host in UW_LOGIN_HOSTS - {'canvas.uw.edu'}
            or host in {'login.microsoftonline.com', 'login.live.com', 'accounts.google.com'}
            or host.endswith('.duosecurity.com')
            or bool(page.locator('input[type="password"]').count()))


def submit_prefilled_login(page, attempted):
    """Submit one already-filled UW login form, without returning credentials.

    Keep unsuccessful pages in attempted so later sources cannot repeatedly
    submit a bad password. MFA and consent pages are left for the user.
    """
    if page in attempted or urlparse(page.url).hostname not in UW_LOGIN_HOSTS:
        return
    try:
        passwords = page.locator('input[type="password"]:visible')
        if passwords.count() != 1:
            return
        password = passwords.first
        if not password.evaluate('element => Boolean(element.value)'):
            return
        form = password.locator('xpath=ancestor::form[1]')
        usernames = form.locator('input[autocomplete="username"], input[type="email"], input[name="user"], input[name="username"], input[name="j_username"], input[id="weblogin_netid"]')
        if not usernames.evaluate_all('nodes => nodes.some(n => Boolean(n.value))'):
            return
        # Do not submit forms that also ask for a verification code.
        if form.locator('input[autocomplete="one-time-code"], input[name="otp"], input[name="passcode"]').count():
            return
        buttons = form.locator('button[type="submit"], input[type="submit"], button:not([type])')
        candidates = []
        for index in range(buttons.count()):
            button = buttons.nth(index)
            label = button.get_attribute('value') or button.inner_text()
            if (re.fullmatch(r'\s*(sign\s*in|log\s*in|login|登录)\s*', label, re.I)
                    and button.is_visible() and button.is_enabled()):
                candidates.append(button)
        if len(candidates) != 1:
            return
        attempted.add(page)
        candidates[0].click(timeout=3000, no_wait_after=True)
        for _ in range(12):
            page.wait_for_timeout(500)
            if not needs_login(page):
                return
    except Exception:
        # A redirect or challenge must not tear down the saved browser session.
        return


def login_message(page, attempted):
    if page in attempted:
        return '已点击浏览器中填好的登录按钮；尚未取得课程访问权限。请查看登录窗口是否需要 MFA 或处理登录错误，完成后再次更新，无需重连。'
    return '已保留登录窗口；未发现可直接提交的已填好 UW 登录表单。请完成登录或 MFA 后再次更新，无需重连。'


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
    def __init__(self, profile=None):
        self.commands = queue.Queue()
        self.lock = threading.Lock()
        self.profile = Path(profile) if profile else Path(__file__).resolve().parent / 'data/course-browser'
        self.state = {"status": "disconnected", "message": "更新检索时自动恢复本机课程浏览器会话；首次登录可使用“连接课程浏览器”。"}
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
        if self.status()['status'] in {'disconnected', 'unavailable'}:
            self.set_state('connecting', '正在自动恢复已保存的课程浏览器会话。')
        try: return self.submit("read", url).result(timeout=70)
        except Exception: return {"url": url, "status": "unavailable", "message": "浏览器读取失败或超时，请检查登录状态。"}

    def disconnect(self):
        self.submit("disconnect")
        return {"status": "disconnecting", "message": "正在关闭课程浏览器；会话保留，下次更新检索时自动恢复。"}

    def run(self):
        context = manager = playwright = None
        login_pages = {}
        attempted = set()
        def context_closed(*_):
            nonlocal context
            context = None
            login_pages.clear()
            attempted.clear()
            self.set_state('disconnected', '课程浏览器已关闭；下次更新检索时自动恢复保存的会话。')
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
                        login_pages.clear()
                        self.set_state("disconnected", "课程浏览器已关闭；下次更新检索时自动恢复保存的会话。")
                continue
            try:
                if action == "disconnect":
                    if context: context.close()
                    if manager: manager.stop()
                    context = manager = None
                    login_pages.clear()
                    attempted.clear()
                    self.set_state("disconnected", "课程浏览器已关闭；下次更新检索时自动恢复保存的会话。")
                    future.set_result(self.status())
                    continue
                if not context:
                    if manager:
                        try: manager.stop()
                        except Exception: pass
                    from playwright.sync_api import sync_playwright
                    manager = sync_playwright().start()
                    self.profile.mkdir(parents=True, exist_ok=True)
                    context = manager.chromium.launch_persistent_context(str(self.profile), channel="msedge", headless=False,
                                                                        accept_downloads=False)
                    context.on('close', context_closed)
                    def filter_request(route):
                        try:
                            if route.request.url.startswith(("data:", "blob:")): return route.continue_()
                            beta.public_url(route.request.url)
                            route.continue_()
                        except Exception: route.abort()
                    context.route("**/*", filter_request)
                host = urlparse(url).hostname
                pending = login_pages.get(host)
                if action == 'read' and pending and not pending.is_closed():
                    submit_prefilled_login(pending, attempted)
                    if needs_login(pending):
                        future.set_result({'url': url, 'status': 'login_required', 'message': login_message(pending, attempted)})
                        continue
                    login_pages.pop(host, None)
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                if action == "connect":
                    page.wait_for_timeout(1200)
                    submit_prefilled_login(page, attempted)
                    login_pages[host] = page
                    self.set_state("connected", login_message(page, attempted) if needs_login(page)
                                   else "课程浏览器已打开并通过登录页面；课程访问权限将在检索时核实。")
                    future.set_result(self.status())
                    continue
                page.wait_for_timeout(1200)
                if needs_login(page):
                    submit_prefilled_login(page, attempted)
                    if not needs_login(page):
                        page.goto(url, wait_until='domcontentloaded', timeout=10000)
                extracted = page.locator("body").inner_text(timeout=10000)
                text = extracted[:100000]
                final = page.url
                login = needs_login(page)
                links = page.locator("a[href]").evaluate_all("nodes => nodes.map(n => ({url:n.href,title:n.innerText})).slice(0,500)")
                result = {"url": url, "final_url": final, "status": "login_required" if login else "read" if len(text.strip()) >= 100 else "unavailable",
                          "message": login_message(page, attempted) if login else "已读取浏览器页面；浏览可能触发平台的阅读标记，不能据此推断整项完成。",
                          "text": "" if login else text, "links": [] if login else links, "truncated": len(extracted) > 100000}
                if result["truncated"]: result["message"] += "已达到内容上限，本次为部分读取。"
                if login:
                    login_pages[host] = page
                    self.set_state('connected', '会话已自动恢复；有平台需要在已打开的窗口中完成登录或 MFA。')
                else:
                    page.close()
                    self.set_state("connected", "课程浏览器会话已恢复并可用；各平台登录状态在读取时核实。")
                future.set_result(result)
            except Exception:
                context = None
                login_pages.clear()
                if manager:
                    try: manager.stop()
                    except Exception: pass
                manager = None
                self.set_state("unavailable", "课程浏览器不可用，请运行 setup_retrieval.ps1，或检查 Edge 与登录窗口。")
                future.set_result({"url": url, "status": "unavailable", "message": self.status()["message"]})


BROWSER = BrowserCollector()
