"""Local-only UW course watch panel. Uses only the Python standard library."""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import uuid
import beta
import retrieval_flow
from types import SimpleNamespace
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SNAPSHOT = ROOT / "snapshot.json"
MANUAL = DATA / "manual_import.json"
STATE = DATA / "user_state.json"
HISTORY = DATA / "history.json"
LOCK = threading.RLock()
MAX_BODY = 2 * 1024 * 1024
HEADER = "X-UW-Course-Panel"


def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return copy.deepcopy(fallback)


def atomic_write(path: Path, value) -> None:
    DATA.mkdir(exist_ok=True)
    if path.exists():
        backup = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=DATA)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def parse_date(value):
    if not value or not isinstance(value, str): return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try: return dt.datetime.combine(dt.date.fromisoformat(value), dt.time())
        except ValueError: return None


def validate_snapshot(s):
    if not isinstance(s, dict): raise ValueError("根对象必须是 JSON object")
    if s.get("schema_version") != 1: raise ValueError("只支持 schema_version: 1")
    term = s.get("term")
    if not isinstance(term, dict) or not all(isinstance(term.get(k), str) and term[k] for k in ("id", "name", "timezone")):
        raise ValueError("term 缺少 id、name 或 timezone")
    courses, tasks = s.get("courses"), s.get("tasks")
    if not isinstance(courses, list) or not isinstance(tasks, list): raise ValueError("courses 和 tasks 必须为数组")
    ids = set()
    course_ids = set()
    for c in courses:
        if not isinstance(c, dict) or not isinstance(c.get("id"), str) or not c.get("id"):
            raise ValueError("每门课程都需要非空 id")
        if c["id"] in course_ids: raise ValueError("课程 id 重复：" + c["id"])
        course_ids.add(c["id"])
    for task in tasks:
        if not isinstance(task, dict) or not isinstance(task.get("id"), str) or not task.get("id"):
            raise ValueError("每个任务都需要稳定的非空 id")
        if task["id"] in ids: raise ValueError("任务 id 重复：" + task["id"])
        if task.get("course_id") not in course_ids: raise ValueError("任务引用了不存在的 course_id：" + str(task.get("course_id")))
        if not isinstance(task.get("title"), str) or not task["title"]: raise ValueError("任务缺少 title：" + task["id"])
        if task.get("due") is not None and parse_date(task["due"]) is None: raise ValueError("due 时间格式无效：" + task["id"])
        ids.add(task["id"])
    return s


def source_snapshot():
    return read_json(SNAPSHOT, None)


def task_snapshot():
    snap = source_snapshot()
    if not snap: return None
    local = read_json(DATA / "manual_tasks.json", {}).get("terms", {}).get(snap["term"]["id"], {})
    snap = copy.deepcopy(snap)
    tasks = {t["id"]: t for t in snap.get("tasks", [])}
    tasks.update(local.get("tasks", {}))
    snap["tasks"] = [t for tid, t in tasks.items() if tid not in local.get("deleted", {})]
    return snap


def change_local_task(body):
    snap = source_snapshot()
    if not snap: raise ValueError("当前没有课程快照")
    store = read_json(DATA / "manual_tasks.json", {"terms": {}})
    local = store.setdefault("terms", {}).setdefault(snap["term"]["id"], {"tasks": {}, "deleted": {}})
    action = body.get("action")
    if action == "add":
        title, course = body.get("title"), body.get("course_id")
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > 160: raise ValueError("请填写不超过 160 字符的任务标题")
        if course not in {c["id"] for c in snap["courses"]}: raise ValueError("请选择当前课程")
        kind = body.get("kind", "homework")
        if kind not in {"homework", "project", "quiz", "exam", "participation", "preparation", "class", "extra_credit"}: raise ValueError("任务分类无效")
        due, description, source = body.get("due") or None, body.get("description", ""), body.get("source_url", "")
        if due is not None and (not isinstance(due, str) or parse_date(due) is None or len(due) > 10 and parse_date(due).tzinfo is None): raise ValueError("截止时间需为日期或带时区的时间")
        if not isinstance(description, str) or len(description) > 12000: raise ValueError("任务详情最多 12000 字符")
        if not isinstance(source, str) or len(source) > 2000 or source and (urlparse(source).scheme not in {"https", "http"} or not urlparse(source).hostname): raise ValueError("来源链接无效")
        tid = "manual-" + uuid.uuid4().hex
        task = {"id": tid, "course_id": course, "title": title.strip(), "kind": kind, "due": due, "description": description, "source_url": source, "certainty": "verified" if due else "needs_confirmation", "manual": True, "source_note": "手动添加", "created_at": iso_now()}
        local["tasks"][tid] = task
    elif action in {"delete", "restore"}:
        tid = body.get("id")
        if tid not in {t["id"] for t in snap["tasks"]} | local["tasks"].keys(): raise ValueError("任务不存在")
        if action == "delete": local["deleted"][tid] = {"at": iso_now()}
        else: local["deleted"].pop(tid, None)
    else: raise ValueError("任务操作无效")
    atomic_write(DATA / "manual_tasks.json", store)
    return {"ok": True, "id": tid}

def merge_snapshot(old, incoming):
    """Never erase a prior task merely because a single source run omitted it."""
    if not old or old.get("term", {}).get("id") != incoming.get("term", {}).get("id"): return incoming
    result = copy.deepcopy(incoming)
    now = {t["id"]: t for t in result.get("tasks", [])}
    for task in old.get("tasks", []):
        if task.get("id") not in now: result["tasks"].append(task)
    return result

def build_ics(snapshot):
    """Export only confirmed, unfinished tasks. Date-only values remain all-day."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//UW Course Monitor//EN"]
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for task in snapshot.get("tasks", []):
        if task.get("lifecycle") in {"cancelled", "excluded"}: continue
        if task.get("user_completed") or task.get("source_status") == "completed" or task.get("certainty") != "verified" or not task.get("due"): continue
        raw = task["due"]
        if len(raw) == 10:
            start = "DTSTART;VALUE=DATE:" + raw.replace("-", "")
            end = ""
        else:
            parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
            start = "DTSTART:" + parsed.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            end = ""
            if task.get("end") and len(task["end"]) > 10:
                ended = dt.datetime.fromisoformat(task["end"].replace("Z", "+00:00"))
                end = "DTEND:" + ended.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        title = str(task.get("title", "")).replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;")
        code = str(next((c.get("code", "") for c in snapshot.get("courses", []) if c.get("id") == task.get("course_id")), ""))
        event = ["BEGIN:VEVENT", f"UID:{task['id']}@uw-course-monitor", f"DTSTAMP:{stamp}", start]
        if end: event.append(end)
        event.append(f"SUMMARY:{code} · {title}".strip(" ·"))
        if task.get("source_url"): event.append("URL:" + str(task["source_url"]))
        event.append("END:VEVENT"); lines += event
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def changes_between(old, new):
    if not old: return [{"at": iso_now(), "type": "import", "message": "已导入首个手动快照"}]
    before = {x["id"]: x for x in old.get("tasks", [])}; after = {x["id"]: x for x in new.get("tasks", [])}
    result = []
    for tid in sorted(after.keys() - before.keys()): result.append({"at": iso_now(), "type": "added", "task_id": tid, "message": "新增任务：" + after[tid].get("title", tid)})
    for tid in sorted(before.keys() - after.keys()): result.append({"at": iso_now(), "type": "removed", "task_id": tid, "message": "源快照不再列出：" + before[tid].get("title", tid)})
    for tid in sorted(before.keys() & after.keys()):
        for field, label in (("due", "截止时间"), ("title", "标题"), ("certainty", "确认状态"), ("points", "分值"), ("weight", "权重")):
            if before[tid].get(field) != after[tid].get(field):
                result.append({"at": iso_now(), "type": "changed", "task_id": tid, "message": f"{after[tid].get('title', tid)}：{label}已更新"})
    return result


def merged_snapshot():
    snap = task_snapshot()
    if not snap: return None
    snap = copy.deepcopy(snap)
    states = read_json(STATE, {"tasks": {}}).get("tasks", {})
    for task in snap.get("tasks", []):
        saved = states.get(task["id"], {})
        task["user_completed"] = bool(saved.get("completed", False))
        task["user_note"] = str(saved.get("note", ""))[:4000]
    return snap


class App(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, fmt, *args): print("[uw-course-monitor] " + fmt % args)
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline';")
        super().end_headers()
    def send_json(self, status, payload):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def allowed(self):
        host = self.headers.get("Host", "").lower()
        origin = self.headers.get("Origin", "")
        port = self.server.server_port
        allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        return host in allowed_hosts and (not origin or origin.lower() in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"})
    def read_body(self):
        if not self.allowed() or self.headers.get(HEADER) != "local-ui": raise PermissionError("请求来源未获允许")
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_BODY: raise ValueError("请求体为空或超过 2 MB 限制")
        return json.loads(self.rfile.read(length).decode("utf-8"))
    def do_GET(self):
        if self.path == '/api/retrieval/gmail':
            if not self.allowed(): return self.send_json(403, {'error': '请求来源未获允许'})
            return self.send_json(200, retrieval_flow.gmail_collector.status(SimpleNamespace(**globals())))
        if self.path.startswith("/api/retrieval/runs/") or self.path in ("/api/retrieval/latest", "/api/retrieval/connections", "/api/retrieval/recent"):
            if not self.allowed(): return self.send_json(403, {"error": "请求来源未获允许"})
            module = SimpleNamespace(**globals())
            try:
                if self.path == "/api/retrieval/connections": return self.send_json(200, retrieval_flow.connections())
                if self.path == "/api/retrieval/latest": return self.send_json(200, retrieval_flow.latest(module))
                if self.path == "/api/retrieval/recent": return self.send_json(200, retrieval_flow.recent(module))
                return self.send_json(200, retrieval_flow.public_job(retrieval_flow.read(module, self.path.rsplit("/", 1)[-1])))
            except ValueError as e: return self.send_json(404, {"error": str(e)})
        if self.path.startswith("/api/retrieval/job/"):
            if not self.allowed(): return self.send_json(403, {"error": "请求来源未获允许"})
            try: return self.send_json(200, beta.retrieval_status(self.path.rsplit("/", 1)[-1]))
            except ValueError as e: return self.send_json(404, {"error": str(e)})
        if self.path == "/api/retrieval/settings":
            if not self.allowed(): return self.send_json(403, {"error": "请求来源未获允许"})
            return self.send_json(200, beta.load_settings(SimpleNamespace(**globals())))
        if self.path == "/api/data":
            snap = merged_snapshot()
            if not snap: return self.send_json(404, {"error": "还没有 snapshot.json。请放入符合 schema v1 的快照后刷新。"})
            return self.send_json(200, snap)
        if self.path == "/api/history": return self.send_json(200, read_json(HISTORY, []))
        if self.path == "/api/ics":
            if not self.allowed(): return self.send_json(403, {"error": "请求来源未获允许"})
            raw = build_ics(merged_snapshot() or {}).encode("utf-8")
            self.send_response(200); self.send_header("Content-Type", "text/calendar; charset=utf-8"); self.send_header("Content-Disposition", "attachment; filename=uw-uncompleted.ics"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); return self.wfile.write(raw)
        if self.path.startswith("/api/"): return self.send_json(404, {"error": "未知 API"})
        static_files = ("/", "/index.html", "/app.js", "/style.css", "/retrieval.html", "/retrieval.js", "/retrieval.css", "/retrieval_assistant.js", "/retrieval_assistant.css", "/gmail.html", "/gmail.js",
                        "/assets/uw-logo.svg", "/assets/uw-campus.jpg", "/assets/fonts.css",
                        "/assets/font-1.ttf", "/assets/font-2.ttf",
                        "/assets/font-3.ttf", "/assets/font-4.ttf",
                        "/assets/noto-sc-400.ttf", "/assets/noto-sc-600.ttf")
        if self.path not in static_files:
            return self.send_json(404, {"error": "本地静态文件不可访问"})
        return super().do_GET()
    def do_POST(self):
        try:
            body = self.read_body()
            if self.path == "/api/tasks":
                with LOCK: result = change_local_task(body)
                return self.send_json(200, result)
            if self.path.startswith("/api/retrieval/"):
                module = SimpleNamespace(**globals())
                if self.path == '/api/retrieval/gmail/settings':
                    return self.send_json(200, retrieval_flow.gmail_collector.configure(module, body))
                if self.path == '/api/retrieval/gmail/connect':
                    return self.send_json(202, retrieval_flow.gmail_collector.connect(module))
                if self.path == '/api/retrieval/gmail/disconnect':
                    return self.send_json(200, retrieval_flow.gmail_collector.disconnect(module))
                if self.path == "/api/retrieval/connect":
                    settings = beta.load_settings(module)
                    if body.get("url") not in {u for c in settings["courses"] for u in c["sources"]}: raise ValueError("请使用已保存的课程来源连接浏览器。")
                    return self.send_json(202, retrieval_flow.course_collector.BROWSER.connect(body["url"]))
                if self.path == "/api/retrieval/disconnect":
                    return self.send_json(202, retrieval_flow.course_collector.BROWSER.disconnect())
                if self.path == "/api/retrieval/messages":
                    return self.send_json(202, retrieval_flow.message(module, body.get("id"), body.get("content")))
                if self.path == "/api/retrieval/cancel":
                    return self.send_json(200, retrieval_flow.cancel(module, body.get("id")))
                with LOCK:
                    if self.path == "/api/retrieval/run":
                        return self.send_json(202, retrieval_flow.start(module, body.get("course_id", "all")))
                    if self.path == "/api/retrieval/resolve":
                        return self.send_json(200, retrieval_flow.resolve(module, body))
                    if self.path == "/api/retrieval/settings":
                        settings = beta.validate_settings(body, source_snapshot())
                        atomic_write(DATA / "retrieval_settings.json", settings)
                        return self.send_json(200, {"ok": True})
                    if self.path == "/api/retrieval/request":
                        return self.send_json(200, beta.request_bundle(module, body.get("course_id", "all")))
                    if self.path == "/api/retrieval/start":
                        return self.send_json(202, beta.start_retrieval(module, body.get("course_id", "all")))
                    if self.path == "/api/retrieval/preview":
                        return self.send_json(200, beta.prepare_preview(module, body.get("snapshot")))
                    if self.path == "/api/retrieval/apply":
                        return self.send_json(200, beta.apply_preview(module, body.get("id")))
                return self.send_json(404, {"error": "未知检索操作"})
            if self.path == "/api/task-state":
                tid = body.get("id"); completed = body.get("completed"); note = body.get("note", "")
                if not isinstance(tid, str) or not isinstance(completed, bool) or not isinstance(note, str) or len(note) > 4000: raise ValueError("任务状态字段无效")
                snap = task_snapshot()
                if not snap or tid not in {t.get("id") for t in snap.get("tasks", [])}: raise ValueError("任务不存在于当前快照")
                with LOCK:
                    state = read_json(STATE, {"tasks": {}}); state.setdefault("tasks", {})[tid] = {"completed": completed, "note": note, "updated_at": iso_now()}
                    if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_BODY: raise ValueError("本地状态数据超过大小限制")
                    atomic_write(STATE, state)
                return self.send_json(200, {"ok": True})
            if self.path == "/api/import":
                incoming = validate_snapshot(body.get("snapshot"))
                with LOCK:
                    previous = source_snapshot(); snap = merge_snapshot(previous, incoming); changes = changes_between(previous, snap)
                    atomic_write(SNAPSHOT, snap)
                    history = read_json(HISTORY, []); history = (changes + history)[:500]; atomic_write(HISTORY, history)
                return self.send_json(200, {"ok": True, "changes": changes, "count": len(changes)})
            return self.send_json(404, {"error": "未知 API"})
        except PermissionError as e: self.send_json(403, {"error": str(e)})
        except (ValueError, json.JSONDecodeError) as e: self.send_json(400, {"error": str(e)})
        except Exception as e:
            print("API error:", repr(e), file=sys.stderr); self.send_json(500, {"error": "本地保存失败；请检查 data 文件夹权限。"})


def main():
    p = argparse.ArgumentParser(); p.add_argument("--port", type=int, default=8765); args = p.parse_args()
    if args.port != 8765: raise SystemExit("本应用固定使用端口 8765。")
    os.chdir(ROOT); DATA.mkdir(exist_ok=True)
    retrieval_flow.recover(SimpleNamespace(**globals()))
    print("UW Course Monitor: http://127.0.0.1:8765")
    ThreadingHTTPServer(("127.0.0.1", 8765), App).serve_forever()
if __name__ == "__main__": main()
