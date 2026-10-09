"""Browser lifecycle tests with a fake browser; no credentials or real network."""
import tempfile
import threading
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
from course_collector import BrowserCollector, submit_prefilled_login, needs_login

URL = 'https://example.edu/course'
class Page:
    def __init__(self, context):
        self.context = context; self.url = 'about:blank'; self.closed = False; self.login = False
    def goto(self, url, **kwargs):
        self.url = 'https://example.edu/login' if self.context.login else url
        self.login = self.context.login
    def wait_for_timeout(self, milliseconds): pass
    def locator(self, selector):
        return SimpleNamespace(count=lambda: int(self.login),
            inner_text=lambda **kwargs: 'Published course assignments and deadlines. ' * 6,
            evaluate_all=lambda expression: [])
    def is_closed(self): return self.closed
    def close(self): self.closed = True

class Context:
    def __init__(self, login):
        self.login = login; self.pages = [Page(self)]; self.closed = False; self.on_close = lambda: None
    def new_page(self):
        page = Page(self); self.pages.append(page); return page
    def route(self, *args): pass
    def on(self, event, callback):
        assert event == 'close'; self.on_close = callback
    def close(self):
        self.closed = True; self.pages = []; self.on_close()

class Factory:
    def __init__(self): self.launches = []; self.login = False
    def manager(self):
        manager = SimpleNamespace()
        def launch(profile, **kwargs):
            context = Context(self.login); self.launches.append((profile, kwargs, context)); return context
        manager.chromium = SimpleNamespace(launch_persistent_context=launch)
        manager.start = lambda: manager
        manager.stop = lambda: None
        return manager

Path('work').mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(dir='work', prefix='browser-session-test-') as directory:
    factory = Factory(); module = ModuleType('playwright.sync_api'); module.sync_playwright = factory.manager
    with patch.dict('sys.modules', {'playwright.sync_api': module}):
        collector = BrowserCollector(Path(directory) / 'profile')
        assert collector.status()['status'] == 'disconnected'
        # Update can read directly, with no connect call.
        assert collector.read(URL)['status'] == 'read'
        assert len(factory.launches) == 1
        assert collector.read(URL)['status'] == 'read' and len(factory.launches) == 1
        # Closing Edge reopens the SAME saved profile on the very next read.
        factory.launches[0][2].close()
        assert collector.read(URL)['status'] == 'read' and len(factory.launches) == 2
        assert factory.launches[0][0] == factory.launches[1][0]
        assert not factory.launches[1][1]['headless']
        collector.submit('disconnect').result(timeout=2)
        factory.login = True
        result = collector.read(URL)
        assert result['status'] == 'login_required'
        context = factory.launches[-1][2]
        login_page = context.pages[-1]
        assert not login_page.closed
        count = len(context.pages)
        assert collector.read(URL + '/assignments')['status'] == 'login_required'
        assert len(context.pages) == count and not login_page.closed
        # User finishes sign-in; subsequent reads use the same context automatically.
        login_page.login = False; login_page.url = URL; context.login = False; factory.login = False
        assert collector.read(URL)['status'] == 'read'
        assert not login_page.closed
        assert len(factory.launches) == 3
        collector.submit('disconnect').result(timeout=2)
        assert collector.read(URL)['status'] == 'read' and len(factory.launches) == 4
        collector.submit('disconnect').result(timeout=2)
print('PASS automatic restore, same profile reuse, browser close and retained single login window')


class AuthPage:
    """Only booleans leave the fake form, matching the production contract."""
    def __init__(self, filled=True, outcome='success', host='idp.u.washington.edu', otp=False):
        self.url = 'https://' + host + '/idp/profile/SAML2/Redirect/SSO'
        self.filled = filled; self.outcome = outcome; self.otp = otp; self.clicks = 0
        self.button = SimpleNamespace(get_attribute=lambda name: 'Sign in', inner_text=lambda: 'Sign in',
                                      is_visible=lambda: True, is_enabled=lambda: True, click=self.click)
        self.form = SimpleNamespace(locator=self.form_locator)
        self.password = SimpleNamespace(evaluate=lambda expression: self.filled,
                                        locator=lambda selector: self.form)
    def form_locator(self, selector):
        if 'one-time-code' in selector:
            return SimpleNamespace(count=lambda: int(self.otp))
        if selector.startswith('button'):
            return SimpleNamespace(count=lambda: 1, nth=lambda index: self.button)
        return SimpleNamespace(evaluate_all=lambda expression: self.filled)
    def locator(self, selector):
        return SimpleNamespace(count=lambda: int('idp.u.washington.edu' in self.url or '/SSO' in self.url), first=self.password)
    def click(self, **kwargs):
        self.clicks += 1
    def wait_for_timeout(self, milliseconds):
        if self.clicks and self.outcome == 'success':
            self.url = 'https://canvas.uw.edu/courses/1920200'
        elif self.clicks and self.outcome == 'mfa':
            self.url = 'https://api-example.duosecurity.com/frame/prompt'


for outcome in ('success', 'failure', 'mfa'):
    page = AuthPage(outcome=outcome); attempted = set()
    submit_prefilled_login(page, attempted)
    assert page.clicks == 1
    assert needs_login(page) == (outcome != 'success')
    submit_prefilled_login(page, attempted)
    assert page.clicks == 1, 'Never resubmit credentials after failure or MFA'
for options in ({'filled': False}, {'otp': True}, {'host': 'untrusted.example'}):
    page = AuthPage(**options)
    submit_prefilled_login(page, set())
    assert page.clicks == 0
page = AuthPage(filled=False); attempted = set()
submit_prefilled_login(page, attempted)
page.filled = True  # Password-manager autofill may arrive after the first read.
submit_prefilled_login(page, attempted)
assert page.clicks == 1 and not needs_login(page)
print('PASS prefilled UW sign-in, redirect, MFA retention, failed-login deduplication and delayed autofill')


class AutoPage(AuthPage, Page):
    def __init__(self, context):
        AuthPage.__init__(self)
        self.context = context; self.closed = False; self.login = False
    def goto(self, url, **kwargs):
        self.url = 'https://idp.u.washington.edu/idp/profile/SAML2/Redirect/SSO' if self.context.login else url
        self.login = self.context.login
    def locator(self, selector):
        if 'idp.u.washington.edu' in self.url:
            return AuthPage.locator(self, selector)
        return Page.locator(self, selector)
    def wait_for_timeout(self, milliseconds):
        AuthPage.wait_for_timeout(self, milliseconds)
        if self.clicks:
            self.context.login = self.login = False


class AutoContext(Context):
    def new_page(self):
        page = AutoPage(self); self.pages.append(page); return page


with tempfile.TemporaryDirectory(dir='work', prefix='browser-autologin-test-') as directory:
    factory = Factory(); factory.login = True
    module = ModuleType('playwright.sync_api'); module.sync_playwright = factory.manager
    with patch.dict('sys.modules', {'playwright.sync_api': module}), patch(__name__ + '.Context', AutoContext):
        collector = BrowserCollector(Path(directory) / 'profile')
        result = collector.read('https://canvas.uw.edu/courses/1920200/assignments')
        assert result['status'] == 'read', result
        assert result['final_url'].endswith('/assignments')
        page = factory.launches[0][2].pages[-1]
        assert page.clicks == 1 and page.closed
        collector.submit('disconnect').result(timeout=2)
print('PASS same retrieval continues to original assignment page after automatic sign-in')
