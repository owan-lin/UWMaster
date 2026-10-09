"""Regressions for repeated decisions, changed evidence and equivalent dates."""
import copy
import datetime as dt
from pathlib import Path
import tempfile
from types import SimpleNamespace
import retrieval_flow as flow
from retrieval_merge import reconcile

BASE = {'term': {'id': 'test'}, 'courses': [{'id': 'c'}], 'tasks': [
    {'id': 'hw', 'course_id': 'c', 'title': 'HW1', 'kind': 'homework', 'due': '2027-10-21T23:59:00-07:00',
     'description': 'Do the work.', 'certainty': 'verified'}]}
URL = 'https://example.edu/assignment'
job = {'id': 'old', 'status': 'finished', 'started_at': '2026-10-09T12:00:00+00:00', 'messages': [],
       'base': BASE, 'request': {'project_rules': 'Mandatory work', 'common_rules': 'Preserve state',
                                'courses': [{'course_id': 'c', 'requirements': 'Assignments'}]},
       'report': {'conflicts': [], 'notices': [], 'changes': []}}
old = {'id': 'first-wording', 'task_id': 'hw', 'field': 'rules', 'message': 'One wording', 'source_url': URL,
       'evidence': 'The deadline is October 21.', 'resolved': True, 'resolution': 'keep'}
new = {**old, 'id': 'different-wording', 'message': 'A different wording', 'resolved': False,
       'evidence': 'The deadline is\n October 21.'}
assert flow.issue_key('conflicts', old, job) == flow.issue_key('conflicts', new, job)
assert flow.issue_key('conflicts', old, job) != flow.issue_key('conflicts', {**new, 'evidence': 'The deadline is October 22.'}, job)
changed = copy.deepcopy(job); changed['request']['courses'][0]['requirements'] = 'New policy'
assert flow.issue_key('conflicts', old, job) != flow.issue_key('conflicts', new, changed)
changed = copy.deepcopy(job); changed['base']['tasks'][0]['due'] = '2027-10-23'
assert flow.issue_key('conflicts', old, job) != flow.issue_key('conflicts', new, changed)
Path('work').mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(dir='work', prefix='noise-test-') as directory:
    fake = SimpleNamespace(DATA=Path(directory))
    job['report']['conflicts'] = [old]; flow.save(fake, job)
    latest = copy.deepcopy(job); latest['id'] = 'new'; latest['started_at'] = '2026-10-09T13:00:00+00:00'
    latest['report']['conflicts'] = [new]; flow.save(fake, latest)
    result = flow.read(fake, 'new')
    assert result['report']['conflicts'][0]['resolved']
    assert result['report']['conflicts'][0]['id'] == new['id']
    assert '0 项待处理' in result['message']
    # A new quoted date reopens the issue even after a previous keep decision.
    latest['report']['conflicts'][0]['evidence'] = 'The deadline is October 22.'
    flow.save(fake, latest)
    assert not flow.read(fake, 'new')['report']['conflicts'][0]['resolved']

def observation(url, due, description='Do the work.'):
    return {'task_id': 'hw', 'course_id': 'c', 'source_url': url, 'source_key': 'hw',
            'evidence': 'Assignment deadline and instructions.', 'blockers': [],
            'fields': [{'name': 'due', 'value_json': '"' + due + '"', 'explicit_clear': False},
                       {'name': 'description', 'value_json': '"' + description + '"', 'explicit_clear': False}]}
other = 'https://example.edu/schedule'
evidence = [{'url': url, 'status': 'read', 'text': 'Assignment deadline and instructions.', 'course_ids': ['c']} for url in (URL, other)]
candidate, report = reconcile(BASE, BASE, {'observations': [observation(URL, '2027-10-22T06:59:00+00:00'),
    observation(other, '2027-10-21T23:59:00-07:00', 'Do  the work.')]}, evidence, {'c'},
    dt.datetime(2026, 10, 9, tzinfo=dt.timezone.utc), {'hw': {'completed': True}})
assert not report['conflicts'] and not report['notices'] and not report['changes']
candidate, report = reconcile(BASE, BASE, {'observations': [observation(URL, '2027-10-22T06:59:00+00:00'),
    observation(other, '2027-10-23T06:59:00+00:00')]}, evidence, {'c'}, dt.datetime(2026, 10, 9, tzinfo=dt.timezone.utc))
assert report['conflicts'][0]['field'] == 'due'
print('PASS paraphrase decisions, changed evidence/rules, equivalent timezones and real conflicts')
