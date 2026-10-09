"""Browser lifecycle tests with a fake browser; no credentials or real network."""
import tempfile
import threading
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
from course_collector import BrowserCollector

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
