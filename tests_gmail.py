"""Gmail evidence and mixed-source workflow tests. No real mailbox access."""
import base64
import copy
import datetime as dt
from email.message import EmailMessage
import json
from pathlib import Path
import tempfile
import threading
import time
import sys
from types import SimpleNamespace
from unittest.mock import patch
import gmail_collector as gmail
import retrieval_flow as flow
import server

BASE = {'schema_version': 1, 'term': {'id': 'test', 'name': 'Test', 'start': '2026-09-30', 'timezone': 'America/Los_Angeles'},
        'courses': [{'id': 'c', 'code': 'CSE 123', 'title': 'Test', 'url': 'https://example.edu/course'}],
        'tasks': [{'id': 'hw1', 'course_id': 'c', 'title': 'HW1', 'kind': 'homework', 'due': '2027-10-10', 'certainty': 'verified'}]}
mail = EmailMessage()
mail['From'] = 'teacher@example.edu'
mail['Subject'] = 'CSE 123 HW1 update'
mail['Date'] = 'Thu, 8 Oct 2026 10:00:00 -0700'
mail['Message-ID'] = '<test@example.edu>'
mail.set_content('HW1 deadline is October 12, 2027. Please complete the revised assignment.')
VALUE = {'id': 'abc123', 'threadId': 'def456', 'raw': base64.urlsafe_b64encode(mail.as_bytes()).decode().rstrip('=')}
source = gmail.parse_message(VALUE, 'test%40example.com', {'c'}, '2026-10-09T10:00:00Z')
assert 'HW1 deadline is October 12' in source['text'] and not source['truncated']
mail.add_attachment(b'pdf content', maintype='application', subtype='pdf', filename='syllabus.pdf')
attached = {**VALUE, 'raw': base64.urlsafe_b64encode(mail.as_bytes()).decode()}
assert gmail.parse_message(attached, 'test', {'c'}, 'now')['truncated']
query = gmail.query_for(BASE['courses'][0], BASE['term'], {'queries': {}})
assert 'CSE 123' in query and 'CSE123' in query and 'newer_than' not in query
assert int(query.split('after:')[1].split()[0]) < int(dt.datetime(2026, 9, 30, tzinfo=dt.timezone.utc).timestamp())
observation = {'task_id': 'hw1', 'course_id': 'c', 'source_key': 'hw1', 'source_url': source['url'],
               'evidence': 'HW1 deadline is October 12, 2027.', 'blockers': [],
               'fields': [{'name': 'due', 'value_json': '"2027-10-12"', 'explicit_clear': False}]}

Path('work').mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(dir='work', prefix='gmail-test-') as directory:
    root = Path(directory).resolve(); data = root / 'data'; data.mkdir()
    def write(path, value): path.write_text(json.dumps(value), encoding='utf-8')
    fake = SimpleNamespace(ROOT=root, DATA=data, SNAPSHOT=root / 'snapshot.json', STATE=data / 'user_state.json',
        HISTORY=data / 'history.json', LOCK=threading.RLock(), read_json=server.read_json, atomic_write=write,
        iso_now=server.iso_now, validate_snapshot=server.validate_snapshot)
    fake.source_snapshot = lambda: server.read_json(fake.SNAPSHOT, None)
    write(fake.SNAPSHOT, BASE); write(fake.STATE, {'tasks': {'hw1': {'completed': True, 'note': 'private'}}})
    (root / 'TASK_RULES.md').write_text('Keep completion and notes', encoding='utf-8')
    assert not gmail.status(fake)['connected']
    for client in ({}, {'installed': {'client_id': 'test.apps.googleusercontent.com', 'client_secret': 'secret',
                                    'auth_uri': 'https://evil.example/', 'token_uri': 'https://oauth2.googleapis.com/token'}}):
        try: gmail.configure(fake, {'client': client}); raise AssertionError('invalid client accepted')
        except ValueError: pass
    client = {'installed': {'client_id': 'test.apps.googleusercontent.com', 'client_secret': 'test-only',
                           'auth_uri': 'https://accounts.google.com/o/oauth2/auth', 'token_uri': 'https://oauth2.googleapis.com/token'}}
    gmail.configure(fake, {'client': client})
    assert 'test-only' not in json.dumps(gmail.status(fake))
    # Optional installed OAuth library: verify the worker and read-only scope without opening a browser.
    try:
        import google_auth_oauthlib.flow
    except ImportError:
        pass
    else:
        credentials = SimpleNamespace(scopes=[gmail.SCOPE], granted_scopes=[gmail.SCOPE],
            to_json=lambda: json.dumps({'token': 'test-only', 'token_uri': 'https://oauth2.googleapis.com/token'}))
        auth_flow = SimpleNamespace(run_local_server=lambda **kwargs: credentials)
        revision = gmail.settings(fake)['revision']
        with patch.object(google_auth_oauthlib.flow.InstalledAppFlow, 'from_client_config', return_value=auth_flow) as create:
            gmail.connect(fake)
            for _ in range(100):
                if gmail.status(fake)['status'] != 'connecting': break
                time.sleep(.01)
            assert gmail.status(fake)['connected'] and gmail.settings(fake)['revision'] != revision
            assert create.call_args.args[1] == [gmail.SCOPE]
        gmail.disconnect(fake)
    gmail.configure(fake, {'enabled': True, 'queries': {'c': 'from:teacher@example.edu'}})
    bundle = flow.beta.request_bundle(fake, 'c')
    with patch.object(gmail, 'access_token', side_effect=ValueError('Needs login')):
        failure = gmail.collect(fake, bundle, gmail.settings(fake), lambda: False)
        assert failure[0]['status'] == 'unavailable'
    with patch.object(gmail, 'access_token', return_value='mock'), patch.object(gmail, 'get', side_effect=[
        {'emailAddress': 'test@example.com'}, {'messages': [VALUE], 'nextPageToken': 'next'}, VALUE]):
        evidence = gmail.collect(fake, bundle, gmail.settings(fake), lambda: False)
        assert evidence[0]['truncated'] and evidence[1]['course_ids'] == ['c']
    with patch.object(gmail, 'access_token', return_value='mock'), patch.object(gmail, 'get', side_effect=[
        {'emailAddress': 'test@example.com'}, {}]):
        empty = gmail.collect(fake, bundle, gmail.settings(fake), lambda: False)
        assert len(empty) == 1 and empty[0]['status'] == 'read' and not empty[0]['truncated']
    state_before = fake.STATE.read_bytes()
    web = {'url': BASE['courses'][0]['url'], 'status': 'read', 'text': 'HW1 is due October 11, 2027.', 'message': 'Read', 'links': []}
    def infer(root, payload, schema, cancelled):
        assert 'private' not in json.dumps(payload)
        assert any(s.get('source_type') == 'gmail' for s in payload['evidence'])
        other = {**observation, 'source_url': web['url'], 'evidence': web['text'],
                 'fields': [{'name': 'due', 'value_json': '"2027-10-11"', 'explicit_clear': False}]}
        return {'summary': 'Deadline conflict', 'warnings': [], 'observations': [observation, other]}
    def wait(job):
        for _ in range(200):
            result = flow.read(fake, job['id'])
            if result['status'] != 'running': return result
            time.sleep(.01)
        raise AssertionError('Job did not finish')
    with patch.object(flow.local_codex, 'executable', return_value='mock'), patch.object(flow.local_codex, 'run', infer), \
         patch.object(flow.course_collector, 'public_read', return_value=web), patch.object(gmail, 'collect', return_value=[source]):
        result = wait(flow.start(fake, 'c'))
        assert result['status'] == 'finished', result
        assert result['report']['conflicts'][0]['field'] == 'due'
        assert fake.source_snapshot()['tasks'][0]['due'] == '2027-10-10'
        assert fake.STATE.read_bytes() == state_before
        assert not any('mail.google.com' in s['url'] for s in fake.source_snapshot()['courses'][0]['coverage'])
    def changed(root, payload, schema, cancelled):
        gmail.configure(fake, {'enabled': False})
        return {'summary': '', 'warnings': [], 'observations': [observation]}
    before = fake.SNAPSHOT.read_bytes()
    with patch.object(flow.local_codex, 'executable', return_value='mock'), patch.object(flow.local_codex, 'run', changed), \
         patch.object(flow.course_collector, 'public_read', return_value=web), patch.object(gmail, 'collect', return_value=[source]):
        result = wait(flow.start(fake, 'c'))
        assert result['status'] == 'failed' and fake.SNAPSHOT.read_bytes() == before
    write(data / 'gmail_token.json', {'token': 'test'})
    write(data / 'gmail_token.json.bak', {'token': 'old-test'})
    gmail.disconnect(fake)
    assert not (data / 'gmail_token.json').exists() and not (data / 'gmail_token.json.bak').exists()
    assert not gmail.settings(fake)['enabled']
    if '--http' in sys.argv:
        import http.client
        from http.server import ThreadingHTTPServer
        with patch.object(server, 'DATA', data), patch.object(server, 'SNAPSHOT', fake.SNAPSHOT):
            httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.App)
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            try:
                def request(method, path, body=None, permitted=True):
                    connection = http.client.HTTPConnection('127.0.0.1', httpd.server_port, timeout=5)
                    headers = {'Content-Type': 'application/json'}
                    if permitted: headers['X-UW-Course-Panel'] = 'local-ui'
                    connection.request(method, path, json.dumps(body) if body is not None else None, headers)
                    response = connection.getresponse(); raw = response.read(); connection.close()
                    return response.status, raw
                assert request('GET', '/api/retrieval/gmail')[0] == 200
                assert request('GET', '/gmail.html')[0] == 200
                assert request('GET', '/gmail.js')[0] == 200
                assert request('GET', '/data/gmail_token.json')[0] == 404
                assert request('POST', '/api/retrieval/gmail/settings', {'enabled': True}, False)[0] == 403
                assert request('POST', '/api/retrieval/gmail/settings', {'enabled': True})[0] == 200
                (data / 'gmail_client.json').unlink(missing_ok=True)
                assert request('POST', '/api/retrieval/gmail/connect', {})[0] == 400
                assert request('POST', '/api/retrieval/gmail/disconnect', {})[0] == 200
            finally:
                httpd.shutdown(); httpd.server_close()
print('Gmail parsing, coverage, mixed-source conflict and state protection passed.')
