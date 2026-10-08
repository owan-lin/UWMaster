"""Beta HTTP regressions run against isolated files and a random localhost port."""
import copy
import http.client
import json
import tempfile
import threading
import time
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from pathlib import Path
import server as s

sample = {
    "schema_version": 1, "term": {"id": "test", "name": "Test", "timezone": "America/Los_Angeles"},
    "courses": [{"id": "c", "code": "CSE", "title": "Test", "policy": "Required work", "url": "https://example.edu/course"}],
    "tasks": [{"id": "a", "course_id": "c", "title": "HW1", "due": "2026-10-10", "certainty": "verified", "description": "old"},
              {"id": "b", "course_id": "c", "title": "Quiz", "due": "2026-10-11", "certainty": "verified"}],
}

with tempfile.TemporaryDirectory(prefix="beta-test-", dir=s.ROOT / "work") as directory:
    s.DATA = Path(directory) / "data"
    s.DATA.mkdir()
    s.SNAPSHOT = Path(directory) / "snapshot.json"
    s.STATE = s.DATA / "user_state.json"
    s.HISTORY = s.DATA / "history.json"
    s.SNAPSHOT.write_text(json.dumps(sample), encoding="utf-8")
    s.STATE.write_text(json.dumps({"tasks": {"a": {"completed": True, "note": "keep this"}}}), encoding="utf-8")
    personal_before = s.STATE.read_bytes()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), s.App)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_port

    def request(method, path, body=None, trusted=True):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        headers = {"Content-Type": "application/json", "X-UW-Course-Panel": "local-ui", "Origin": f"http://127.0.0.1:{port}" if trusted else "https://other.example"}
        connection.request(method, path, json.dumps(body) if body is not None else None, headers)
        response = connection.getresponse()
        raw = response.read()
        status = response.status
        is_json = "json" in response.getheader("Content-Type", "")
        connection.close()
        return status, json.loads(raw) if is_json else raw

    try:
        assert request("GET", "/retrieval.html")[0] == 200
        assert request("GET", "/retrieval.js")[0] == 200
        settings = request("GET", "/api/retrieval/settings")[1]
        assert "lecture 非必到" in settings["project_rules"].lower()
        settings["courses"][0]["requirements"] = "Only mandatory work"
        assert request("POST", "/api/retrieval/settings", settings)[0] == 200
        assert request("GET", "/api/retrieval/settings")[1]["courses"][0]["requirements"] == "Only mandatory work"
        bad = copy.deepcopy(settings)
        bad["courses"][0]["sources"] = ["http://example.edu"]
        assert request("POST", "/api/retrieval/settings", bad)[0] == 400
        assert request("POST", "/api/retrieval/settings", settings, trusted=False)[0] == 403
        bundle = request("POST", "/api/retrieval/request", {"course_id": "c"})[1]
        assert "user_note" not in json.dumps(bundle) and "keep this" not in json.dumps(bundle)
        ready = threading.Event()
        def fake_source(url):
            ready.wait(3)
            return {"url": url, "status": "read", "text": "Example source", "message": "Read"}
        with patch.object(s.beta, "retrieve_source", fake_source):
            job = request("POST", "/api/retrieval/start", {"course_id": "c"})[1]
            assert request("GET", "/api/retrieval/job/" + job["id"])[1]["status"] == "running"
            assert request("POST", "/api/retrieval/start", {"course_id": "c"})[0] == 400
            assert request("GET", "/api/data")[0] == 200, "retrieval must not block todo"
            ready.set()
            for _ in range(50):
                result = request("GET", "/api/retrieval/job/" + job["id"])[1]
                if result["status"] == "finished": break
                time.sleep(.02)
            assert result["status"] == "finished" and result["completed"] == 1
        incoming = copy.deepcopy(sample)
        incoming["tasks"] = [incoming["tasks"][0]]  # omitted old task must survive
        incoming["tasks"][0].update(description="new details", user_completed=False, user_note="replace")
        incoming["tasks"].append({"id": "new", "course_id": "c", "title": "HW2", "due": None})
        preview = request("POST", "/api/retrieval/preview", {"snapshot": incoming})[1]
        assert preview["count"] == 2 and "description" in preview["changes"][0]["fields"]
        assert json.loads(s.SNAPSHOT.read_text()) == sample, "preview must not change courses"
        assert request("POST", "/api/task-state", {"id": "a", "completed": False, "note": "latest note"})[0] == 200
        personal_before = s.STATE.read_bytes()
        assert request("POST", "/api/retrieval/apply", {"id": preview["id"]})[0] == 200
        assert s.STATE.read_bytes() == personal_before
        updated = request("GET", "/api/data")[1]
        assert len(updated["tasks"]) == 3
        assert updated["tasks"][0]["user_note"] == "latest note"
        assert updated["tasks"][0]["user_completed"] is False
        assert request("POST", "/api/retrieval/apply", {"id": preview["id"]})[0] == 400
        assert request("GET", "/api/ics")[0] == 200
        assert request("GET", "/data/retrieval_settings.json")[0] == 404
        preview = request("POST", "/api/retrieval/preview", {"snapshot": incoming})[1]
        changed = s.source_snapshot()
        changed["tasks"][0]["title"] = "Concurrent edit"
        s.atomic_write(s.SNAPSHOT, changed)
        assert request("POST", "/api/retrieval/apply", {"id": preview["id"]})[0] == 400
        other_term = copy.deepcopy(incoming)
        other_term["term"]["id"] = "other"
        assert request("POST", "/api/retrieval/preview", {"snapshot": other_term})[0] == 400
        add = {"action": "add", "course_id": "c", "title": "Manual assignment", "kind": "homework", "description": "Details", "due": "2026-11-02T09:00:00-08:00"}
        added = request("POST", "/api/tasks", add)[1]["id"]
        assert request("POST", "/api/task-state", {"id": added, "completed": True, "note": "manual note"})[0] == 200
        assert any(t["id"] == added for t in request("GET", "/api/data")[1]["tasks"])
        bad = dict(add, due="2026-11-02T09:00:00")
        assert request("POST", "/api/tasks", bad)[0] == 400
        assert request("POST", "/api/tasks", dict(add, title=""))[0] == 400
        assert request("POST", "/api/tasks", {"action": "delete", "id": "a"})[0] == 200
        assert not any(t["id"] == "a" for t in request("GET", "/api/data")[1]["tasks"])
        # A source import cannot resurrect deletion or erase a manual task.
        assert request("POST", "/api/import", {"snapshot": sample})[0] == 200
        tasks = request("GET", "/api/data")[1]["tasks"]
        assert not any(t["id"] == "a" for t in tasks)
        assert any(t["id"] == added and t["user_note"] == "manual note" for t in tasks)
        assert request("POST", "/api/tasks", {"action": "restore", "id": "a"})[0] == 200
        assert next(t for t in request("GET", "/api/data")[1]["tasks"] if t["id"] == "a")["user_note"] == "latest note"
        assert request("POST", "/api/tasks", {"action": "delete", "id": added})[0] == 200
        assert not any(t["id"] == added for t in request("GET", "/api/data")[1]["tasks"])
        assert request("GET", "/data/manual_tasks.json")[0] == 404
    finally:
        httpd.shutdown()
        httpd.server_close()

print("PASS Beta settings, preview, apply, concurrent updates, personal state and original APIs")
