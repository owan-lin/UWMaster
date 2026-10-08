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


print("PASS field merge, task identity, future scope, state separation and conflicts")
