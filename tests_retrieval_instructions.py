"""Overall and per-course instructions must travel together and stay versioned."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch
import beta
import retrieval_flow as flow
import server

Path('work').mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(dir='work', prefix='instruction-test-') as directory:
    root = Path(directory).resolve(); data = root / 'data'; data.mkdir()
    url = 'https://example.edu/course'
    snapshot = {'schema_version': 1, 'term': {'id': 'test', 'name': 'Test'},
                'courses': [{'id': 'c', 'code': 'C', 'title': 'Test', 'url': url}], 'tasks': []}
    def write(path, value): path.write_text(json.dumps(value), encoding='utf-8')
    fake = SimpleNamespace(ROOT=root, DATA=data, SNAPSHOT=root / 'snapshot.json', STATE=data / 'state.json',
        HISTORY=data / 'history.json', LOCK=threading.RLock(), read_json=server.read_json,
        atomic_write=write, validate_snapshot=server.validate_snapshot, iso_now=server.iso_now)
    fake.source_snapshot = lambda: server.read_json(fake.SNAPSHOT, None)
    write(fake.SNAPSHOT, snapshot); write(fake.STATE, {'tasks': {}})
    (root / 'TASK_RULES.md').write_text('Explicit task rules', encoding='utf-8')
    plan = root / 'RETRIEVAL_WORKFLOW_PLAN.md'
    try: beta.request_bundle(fake, 'c'); raise AssertionError('Missing overall instructions were ignored')
    except ValueError: pass
    plan.write_text('Overall plan v1', encoding='utf-8')
    write(data / 'retrieval_settings.json', {'overall_plan': 'Stale client copy', 'courses': [
        {'course_id': 'c', 'requirements': 'Include required prep work', 'sources': [url]}]})
    bundle = beta.request_bundle(fake, 'c')
    assert bundle['overall_plan'] == 'Overall plan v1'
    assert bundle['courses'][0]['requirements'] == 'Include required prep work'
    assert bundle['project_rules'] == 'Explicit task rules'
    assert bundle['overall_plan_version'] == beta.digest(bundle['overall_plan'])
    initial = fake.SNAPSHOT.read_bytes()
    def inference(root, payload, schema, cancelled):
        request = payload['request']
        assert request['overall_plan'] == 'Overall plan v1'
        assert request['courses'][0]['requirements'] == 'Include required prep work'
        assert 'instruction_policy' in request
        plan.write_text('Overall plan v2', encoding='utf-8')
        return {'summary': 'Nothing changed', 'warnings': [], 'observations': []}
    with patch.object(flow.local_codex, 'executable', return_value='mock'), patch.object(flow.local_codex, 'run', inference), \
         patch.object(flow.course_collector, 'public_read', return_value={'url': url, 'status': 'read', 'text': 'Course text evidence.', 'links': [], 'message': 'Read'}):
        job = flow.start(fake, 'c')
        for _ in range(100):
            result = flow.read(fake, job['id'])
            if result['status'] != 'running': break
            time.sleep(.02)
        assert result['status'] == 'failed' and '规则已修改' in result['message'], result
        assert result['instruction_versions']['overall_plan_version'] == bundle['overall_plan_version']
        assert fake.SNAPSHOT.read_bytes() == initial
        assert beta.request_bundle(fake, 'c')['overall_plan_version'] != bundle['overall_plan_version']
    # Rule changes also invalidate the evidence-based repeated-decision key.
    issue = {'id': 'issue', 'task_id': None, 'field': 'rules', 'evidence': 'Course text evidence.', 'source_url': url}
    a = {'base': snapshot, 'request': bundle}; b = copy.deepcopy(a)
    b['request']['overall_plan_version'] = beta.digest('Overall plan v2')
    assert flow.issue_key('conflicts', issue, a) != flow.issue_key('conflicts', issue, b)
print('PASS overall/course instructions, fresh disk content, frozen versions and changed-plan protection')
