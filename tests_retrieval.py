"""Merge and durable workflow regressions. All writes use temporary project files."""
import copy
import datetime as dt
import json
import tempfile
import time
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import server
import retrieval_flow as flow
from retrieval_merge import reconcile

NOW = dt.datetime(2026, 10, 8, 17, tzinfo=dt.timezone.utc)
URL = "https://example.edu/course"
TEXT = "HW1 is due October 12. HW2 is due October 15. Platform explicitly says not submitted. New instructions are required."
BASE = {"schema_version": 1, "term": {"id": "test", "name": "Test", "timezone": "America/Los_Angeles"},
        "courses": [{"id": "c", "code": "C", "title": "Test", "url": URL}],
        "tasks": [{"id": "a", "course_id": "c", "title": "HW1", "kind": "homework", "due": "2026-10-10", "points": 10, "description": "old", "certainty": "verified"},
                  {"id": "b", "course_id": "c", "title": "Old task", "due": "2026-10-01", "kind": "homework"}]}
EVIDENCE = [{"url": URL, "status": "read", "text": TEXT, "message": "Read", "checked_at": NOW.isoformat()}]


def obs(tid="a", url=URL, blockers=None, **fields):
    return {"task_id": tid, "course_id": "c", "source_url": url, "source_key": "assignment:2", "evidence": "HW1 is due October 12.",
            "fields": [{"name": name, "value_json": json.dumps(value), "explicit_clear": False} for name, value in fields.items()], "blockers": blockers or []}


def merge(observations, current=None, evidence=None, states=None):
    return reconcile(BASE, current or BASE, {"observations": observations}, evidence or EVIDENCE, {"c"}, NOW, states)


candidate, report = merge([obs(due="2026-10-12", points=None, user_completed=False)], states={"a": {"completed": True, "note": "keep"}})
assert candidate["tasks"][0]["due"] == "2026-10-12"
assert candidate["tasks"][0]["points"] == 10
assert "user_completed" not in candidate["tasks"][0]
assert len(candidate["tasks"]) == 2
assert report["changes"][0]["fields"] == ["due"]

candidate, report = merge([obs(tid=None, title="HW2", due="2026-10-15", kind="homework")])
assert len(candidate["tasks"]) == 3
stable = candidate["tasks"][-1]["id"]
again, report = merge([obs(tid=None, title="HW2", due="2026-10-15", kind="homework")], current=candidate)
assert len(again["tasks"]) == 3 and again["tasks"][-1]["id"] == stable
candidate, report = merge([obs(tid=None, title="Unknown deadline", due=None, kind="homework")])
assert candidate["tasks"][-1]["due"] is None
candidate, report = merge([obs(tid=None, title="Past new task", due="2026-10-01", kind="homework")])
assert len(candidate["tasks"]) == 2 and report["rejected"]
candidate, report = merge([obs(tid=None, title="HW1", due="2026-10-15", kind="homework")])
assert len(candidate["tasks"]) == 2 and report["conflicts"][0]["field"] == "identity"

candidate, report = merge([obs(completion_status="unknown")], states={"a": {"completed": True}})
assert not report["notices"]
candidate, report = merge([obs(submission_status="not_submitted")], states={"a": {"completed": True}})
assert report["notices"][0]["field"] == "completion"
candidate, report = merge([obs(description="new instructions")], states={"a": {"completed": True}})
assert report["notices"][0]["field"] == "requirements"

current = copy.deepcopy(BASE)
current["tasks"][0]["due"] = "2026-10-13"
candidate, report = merge([obs(due="2026-10-12", points=12)], current=current)
assert candidate["tasks"][0]["due"] == "2026-10-13" and candidate["tasks"][0]["points"] == 12
assert candidate["tasks"][0]["certainty"] == "needs_confirmation"
assert report["conflicts"][0]["field"] == "due"
candidate, report = merge([obs(due="2026-10-07")])
assert candidate["tasks"][0]["due"] == "2026-10-07", "existing future task can move into past"
other = "https://example.edu/second"
candidate, report = merge([obs(due="2026-10-12"), obs(url=other, due="2026-10-13")], evidence=EVIDENCE + [{**EVIDENCE[0], "url": other}])
assert candidate["tasks"][0]["due"] == BASE["tasks"][0]["due"] and report["conflicts"]
assert candidate["tasks"][0]["needs_review"]
candidate, report = merge([obs(due="2026-10-12", blockers=["规则冲突"]), obs(points=12)])
assert candidate["tasks"][0]["points"] == 10, "blocked task cannot partially bypass a rule conflict"
candidate, report = merge([obs(due="2026-10-12T13:00:00")])
assert candidate["tasks"][0]["due"] == BASE["tasks"][0]["due"] and report["rejected"]
candidate, report = merge([obs(due="2026-10-12")], evidence=[{**EVIDENCE[0], "text": "unrelated content"}])
assert not report["changes"] and report["rejected"]

Path("work").mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix="retrieval-test-", dir="work") as directory:
    root = Path(directory).resolve()
    data = root / "data"
    data.mkdir()
    snapshot = root / "snapshot.json"
    state = data / "user_state.json"
    snapshot.write_text(json.dumps(BASE), encoding="utf-8")
    state.write_text(json.dumps({"tasks": {"a": {"completed": True, "note": "private note"}}}), encoding="utf-8")
    (root / "TASK_RULES.md").write_text("Respect user requirements", encoding="utf-8")
    fake = SimpleNamespace(ROOT=root, DATA=data, SNAPSHOT=snapshot, STATE=state, HISTORY=data / "history.json", LOCK=threading.RLock(),
                           read_json=server.read_json, iso_now=server.iso_now, validate_snapshot=server.validate_snapshot)
    fake.source_snapshot = lambda: server.read_json(snapshot, None)
    def atomic(path, value):
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    fake.atomic_write = atomic
    before = state.read_bytes()
    entered, release = threading.Event(), threading.Event()
    def inference(root, payload, schema, cancelled=None):
        assert "private note" not in json.dumps(payload), "personal notes must not go to inference"
        entered.set()
        release.wait(3)
        return {"summary": "Test inference", "warnings": [], "observations": [obs(due="2027-10-12", submission_status="not_submitted")]}
    with patch.object(flow.local_codex, "executable", return_value="test"), patch.object(flow.local_codex, "run", inference), patch.object(flow.course_collector, "public_read", return_value=EVIDENCE[0]):
        job = flow.start(fake, "c")
        assert entered.wait(3)
        state.write_text(json.dumps({"tasks": {"a": {"completed": True, "note": "new private note"}}}), encoding="utf-8")
        before = state.read_bytes()
        release.set()
        for _ in range(100):
            job = flow.read(fake, job["id"])
            if job["status"] != "running": break
            time.sleep(.02)
        assert job["status"] == "finished", job
        assert state.read_bytes() == before
        assert fake.source_snapshot()["tasks"][0]["due"] == "2027-10-12"
        assert flow.latest(fake)["id"] == job["id"]
        assert "base" not in flow.public_job(job)
        assert "text" not in flow.public_job(job)["sources"][0]
        # Read after a restart, without an in-memory job, still returns results.
        flow.ACTIVE.clear()
        assert flow.read(fake, job["id"])["status"] == "finished"
        assert fake.source_snapshot()["tasks"][1]["id"] == "b"
        notice = job["report"]["notices"][0]
        resolved = flow.resolve(fake, {"id": job["id"], "conflict_id": notice["id"], "selection": "keep"})
        assert resolved["report"]["notices"][0]["resolved"]
        assert fake.source_snapshot()["tasks"][0]["needs_review"] is False
        assert state.read_bytes() == before
    # Cancel while inference is running: no source updates are applied.
    entered.clear(); release.clear()
    previous = snapshot.read_bytes()
    with patch.object(flow.local_codex, "executable", return_value="test"), patch.object(flow.local_codex, "run", inference), patch.object(flow.course_collector, "public_read", return_value=EVIDENCE[0]):
        job = flow.start(fake, "c")
        assert entered.wait(3)
        flow.cancel(fake, job["id"])
        release.set()
        for _ in range(100):
            job = flow.read(fake, job["id"])
            if job["status"] != "running": break
            time.sleep(.02)
        assert job["status"] == "cancelled" and snapshot.read_bytes() == previous
    # Field conflicts can be resolved using recorded evidence; repeated resolution is rejected.
    current = copy.deepcopy(BASE)
    current["tasks"][0]["due"] = "2026-10-13"
    candidate, report = merge([obs(due="2026-10-12")], current=current)
    atomic(snapshot, candidate)
    conflict_job = {"id": "conflict", "status": "finished", "stage": "finished", "started_at": NOW.isoformat(),
                    "base": BASE, "request": {}, "sources": EVIDENCE, "course_ids": ["c"], "total": 1, "completed": 1,
                    "messages": [], "report": report, "message": "Conflict"}
    flow.save(fake, conflict_job)
    conflict_id = report["conflicts"][0]["id"]
    resolved = flow.resolve(fake, {"id": "conflict", "conflict_id": conflict_id, "selection": 0})
    assert fake.source_snapshot()["tasks"][0]["due"] == "2026-10-12"
    assert fake.source_snapshot()["tasks"][0]["certainty"] == "verified"
    assert state.read_bytes() == before
    try: flow.resolve(fake, {"id": "conflict", "conflict_id": conflict_id, "selection": 0})
    except ValueError: pass
    else: raise AssertionError("repeat resolution must be rejected")
    # Crash between snapshot replacement and job completion is recovered idempotently.
    pending_candidate = copy.deepcopy(fake.source_snapshot())
    pending_candidate["tasks"][0]["points"] = 99
    pending_report = {"changes": [{"type": "changed", "task_id": "a", "title": "HW1", "fields": ["points"], "before": fake.source_snapshot()["tasks"][0], "after": pending_candidate["tasks"][0]}], "conflicts": [], "notices": [], "rejected": []}
    conflict_job.update(status="running", pending={"before_digest": flow.beta.digest(fake.source_snapshot()), "candidate": pending_candidate, "report": pending_report})
    flow.save(fake, conflict_job)
    atomic(snapshot, pending_candidate)
    flow.recover(fake)
    assert flow.read(fake, "conflict")["status"] == "finished"
    history_count = len(fake.read_json(history := fake.HISTORY, []))
    flow.recover(fake)
    assert len(fake.read_json(history, [])) == history_count

assert flow.followable("https://courses.cs.washington.edu/courses/cse391/26au/homework/1/", ["https://courses.cs.washington.edu/courses/cse391/26au/"])
assert not flow.followable("https://courses.cs.washington.edu/courses/cse123/26au/homework/1/", ["https://courses.cs.washington.edu/courses/cse391/26au/"])
assert not flow.followable("https://example.edu/course/logout", [URL])

print("PASS evidence merge, future scope, identity, unknown preservation, state separation, conflicts, durable jobs and cancellation")
