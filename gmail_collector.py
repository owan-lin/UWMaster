"""Optional read-only Gmail source for the local application, independent of chat connectors."""
import base64
import datetime as dt
import email.policy
from email.parser import BytesParser
import json
import re
import threading
import sys
import uuid
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import beta

RUNTIME = Path(__file__).resolve().parent / 'work/runtime-packages'
if RUNTIME.is_dir(): sys.path.insert(0, str(RUNTIME))

SCOPE = 'https://www.googleapis.com/auth/gmail.readonly'
API = 'https://gmail.googleapis.com/gmail/v1/users/me/'
LOCK = threading.RLock()
AUTH = {}


def settings(server):
    value = server.read_json(server.DATA / 'gmail_settings.json', {})
    return {'enabled': bool(value.get('enabled')), 'queries': value.get('queries', {}), 'revision': value.get('revision', '')}


def status(server):
    with LOCK:
        value = settings(server)
        token = server.read_json(server.DATA / 'gmail_token.json', {})
        return {**value, 'configured': (server.DATA / 'gmail_client.json').exists(),
                'connected': bool(token.get('refresh_token') or token.get('token')),
                **AUTH.get(str(server.DATA), {'status': 'idle', 'message': '授权在检索时验证。' if token else '尚未连接 Gmail。'})}


def clear_token(server):
    for name in ('gmail_token.json', 'gmail_token.json.bak'):
        (server.DATA / name).unlink(missing_ok=True)


def save_token(server, credentials):
    server.atomic_write(server.DATA / 'gmail_token.json', json.loads(credentials.to_json()))
    (server.DATA / 'gmail_token.json.bak').unlink(missing_ok=True)


def configure(server, body):
    with LOCK:
        if AUTH.get(str(server.DATA), {}).get('status') == 'connecting':
            raise ValueError('Gmail 授权进行中，请完成授权或等待超时。')
        if 'client' in body:
            client = body['client']
            installed = client.get('installed', {}) if isinstance(client, dict) else {}
            if (not isinstance(installed, dict) or not str(installed.get('client_id', '')).endswith('.apps.googleusercontent.com')
                    or not isinstance(installed.get('client_secret'), str)
                    or installed.get('auth_uri') != 'https://accounts.google.com/o/oauth2/auth'
                    or installed.get('token_uri') != 'https://oauth2.googleapis.com/token'):
                raise ValueError('请导入 Google 的桌面应用 OAuth 客户端 JSON。')
            server.atomic_write(server.DATA / 'gmail_client.json', client)
            clear_token(server)
            server.atomic_write(server.DATA / 'gmail_settings.json', {**settings(server), 'revision': uuid.uuid4().hex})
        if 'enabled' in body or 'queries' in body:
            current = settings(server)
            enabled = body.get('enabled', current['enabled'])
            queries = body.get('queries', current['queries'])
            ids = {c['id'] for c in server.source_snapshot()['courses']}
            if not isinstance(enabled, bool) or not isinstance(queries, dict) or any(
                    k not in ids or not isinstance(v, str) or len(v) > 2000 for k, v in queries.items()):
                raise ValueError('邮件检索范围无效。')
            server.atomic_write(server.DATA / 'gmail_settings.json', {**current, 'enabled': enabled, 'queries': queries})
        AUTH.pop(str(server.DATA), None)
        return status(server)


def connect(server):
    # Import optional packages only here; website retrieval works without them.
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        raise ValueError('请先运行 setup_gmail.ps1 安装 Gmail 授权依赖。') from None
    with LOCK:
        if AUTH.get(str(server.DATA), {}).get('status') == 'connecting': return status(server)
        client = server.read_json(server.DATA / 'gmail_client.json', {})
        if not client: raise ValueError('请先导入 Google 桌面应用 OAuth 客户端 JSON。')
        AUTH[str(server.DATA)] = {'status': 'connecting', 'message': '请在 Google 页面授权只读访问；等待最多 3 分钟。'}
    def authorize():
        try:
            flow = InstalledAppFlow.from_client_config(client, [SCOPE], autogenerate_code_verifier=True)
            credentials = flow.run_local_server(host='127.0.0.1', port=0, open_browser=True,
                timeout_seconds=180, prompt='consent',
                authorization_prompt_message='请在浏览器完成 Gmail 授权。',
                success_message='Gmail authorization received. You may close this tab.')
            granted = credentials.granted_scopes or credentials.scopes
            if SCOPE not in granted: raise ValueError('只读邮件权限未获授权。')
            with LOCK:
                save_token(server, credentials)
                server.atomic_write(server.DATA / 'gmail_settings.json', {**settings(server), 'revision': uuid.uuid4().hex})
                AUTH[str(server.DATA)] = {'status': 'connected', 'message': 'Gmail 只读授权已保存。'}
        except Exception:
            with LOCK:
                AUTH[str(server.DATA)] = {'status': 'failed', 'message': 'Gmail 授权未完成；请检查 Google 客户端、测试用户及授权页面后重试。'}
    threading.Thread(target=authorize, daemon=True).start()
    return status(server)


def disconnect(server):
    with LOCK:
        if AUTH.get(str(server.DATA), {}).get('status') == 'connecting':
            raise ValueError('请先结束正在进行的 Google 授权，或等待超时。')
        clear_token(server)
        value = settings(server)
        server.atomic_write(server.DATA / 'gmail_settings.json', {**value, 'enabled': False, 'revision': uuid.uuid4().hex})
        AUTH[str(server.DATA)] = {'status': 'idle', 'message': '本地授权已移除；可在 Google 账号中进一步撤销授权。'}
        return status(server)


def access_token(server):
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request as GoogleRequest
        with LOCK:
            value = server.read_json(server.DATA / 'gmail_token.json', {})
            if not value: raise ValueError('尚未授权 Gmail。')
            if value.get('token_uri') != 'https://oauth2.googleapis.com/token': raise ValueError('Gmail 授权记录无效。')
            credentials = Credentials.from_authorized_user_info(value, [SCOPE])
            if not credentials.valid:
                credentials.refresh(GoogleRequest())
                save_token(server, credentials)
            return credentials.token
    except ImportError:
        raise ValueError('请运行 setup_gmail.ps1 安装 Gmail 授权依赖。') from None
    except Exception:
        raise ValueError('Gmail 授权不可用，请重新连接 Gmail。') from None


def get(token, path, params=None):
    url = API + path + ('?' + urlencode(params) if params else '')
    try:
        with urlopen(Request(url, headers={'Authorization': 'Bearer ' + token}), timeout=20) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
            if len(raw) > 8 * 1024 * 1024: raise ValueError('邮件超过读取大小上限。')
            return json.loads(raw)
    except (HTTPError, URLError, TimeoutError):
        raise ValueError('Gmail API 读取失败，请检查授权及 API 是否启用。') from None


def query_for(course, term, config):
    # Rescan the whole window so edits, replies and older future assignments are not lost.
    start = dt.date.fromisoformat(term.get('start') or dt.date.today().isoformat()) - dt.timedelta(days=30)
    custom = config['queries'].get(course['id'], '').strip()
    code = re.sub(r'[^A-Za-z0-9 ]', '', course.get('code', course['id'])).strip()
    compact = code.replace(' ', '')
    match = custom or ('{"' + code + '" "' + compact + '"}')
    return f'after:{int(dt.datetime.combine(start, dt.time(), dt.timezone.utc).timestamp())} ({match}) -in:trash -in:spam'


def parse_message(value, account, course_ids, checked_at):
    raw = base64.urlsafe_b64decode(value['raw'] + '=' * (-len(value['raw']) % 4))
    message = BytesParser(policy=email.policy.default).parsebytes(raw)
    part = message.get_body(preferencelist=('plain', 'html'))
    text = part.get_content() if part else ''
    if part and part.get_content_type() == 'text/html':
        parser = beta.PageText()
        parser.feed(text)
        text = '\n'.join(parser.parts)
    attachments = [p.get_filename() or 'attachment' for p in message.iter_attachments()] if message.is_multipart() else []
    text = '\n'.join(f'{label}: {message.get(label, "")}' for label in ('From', 'Subject', 'Date', 'Message-ID')) + '\n\n' + text
    partial = bool(attachments) or len(text) > 40000
    return {'url': f'https://mail.google.com/mail/u/{account}/#all/{value["id"]}',
            'status': 'read', 'source_type': 'gmail', 'message_id': value['id'],
            'thread_id': value.get('threadId'), 'course_ids': sorted(course_ids),
            'checked_at': checked_at, 'text': text[:40000], 'links': [], 'truncated': partial,
            'message': '已读取邮件正文。' + ('附件或超出上限的正文未读取，属于部分核查。' if partial else '')}


def collect(server, bundle, config, cancelled):
    """Return per-message evidence plus per-course search coverage, never a zero-mail success on failure."""
    sources, ids = [], {}
    try:
        token = access_token(server)
        # Address routes Gmail links to the same account even in a multi-account browser.
        from urllib.parse import quote
        account = quote(get(token, 'profile')['emailAddress'], safe='')
    except ValueError as exc:
        return [{'url': 'https://mail.google.com/', 'status': 'unavailable', 'source_type': 'gmail_search',
                 'course_ids': [c['course_id'] for c in bundle['courses']], 'text': '', 'links': [],
                 'message': str(exc), 'checked_at': server.iso_now()}]
    courses = {c['id']: c for c in bundle['current_snapshot']['courses']}
    for selected in bundle['courses']:
        if cancelled(): raise ValueError('检索已取消。')
        cid = selected['course_id']
        query = query_for(courses[cid], bundle['term'], config)
        coverage = {'url': 'https://mail.google.com/mail/u/' + account + '/#search/' + quote(query, safe=''),
                    'status': 'read', 'source_type': 'gmail_search', 'course_ids': [cid], 'text': '',
                    'links': [], 'checked_at': server.iso_now(), 'query': query, 'message': ''}
        try:
            page = get(token, 'messages', {'q': query, 'maxResults': 100})
            for value in page.get('messages', []): ids.setdefault(value['id'], set()).add(cid)
            coverage['truncated'] = bool(page.get('nextPageToken'))
            coverage['message'] = f'课程邮件匹配 {len(page.get("messages", []))} 封。' + ('达到 100 封上限，请缩小搜索范围；仅部分核查。' if coverage['truncated'] else '已搜索学期开始前 30 天至今的匹配邮件。')
        except ValueError as exc:
            coverage.update(status='unavailable', message=str(exc))
        sources.append(coverage)
    for mid, course_ids in ids.items():
        if cancelled(): raise ValueError('检索已取消。')
        try:
            if not re.fullmatch(r'[a-fA-F0-9]+', mid): raise ValueError('邮件标识无效。')
            value = get(token, 'messages/' + mid, {'format': 'raw'})
            sources.append(parse_message(value, account, course_ids, server.iso_now()))
        except Exception:
            sources.append({'url': f'https://mail.google.com/mail/u/{account}/#all/{mid}', 'status': 'unavailable',
                'source_type': 'gmail', 'course_ids': sorted(course_ids), 'text': '', 'links': [],
                'checked_at': server.iso_now(), 'message': '这封邮件读取失败，不能视为已核查。'})
    return sources
