"""Course retrieval settings and reviewable updates, isolated from personal state."""
from __future__ import annotations

import copy
import hashlib
import json
import uuid
import concurrent.futures
import ipaddress
import socket
import threading
from html.parser import HTMLParser
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler

JOBS = {}
JOB_LOCK = threading.Lock()


def public_url(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("来源需要使用公开 HTTPS 网页")
    addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(x[4][0]).is_global for x in addresses):
        raise ValueError("来源不能指向本机或内网")


class PublicRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"): self.hidden += 1
        elif tag in ("p", "div", "br", "tr", "li", "h1", "h2", "h3"): self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"): self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden: self.parts.append(data + " ")


def retrieve_source(url):
    result = {"url": url, "status": "unavailable"}
    try:
        public_url(url)
        with build_opener(PublicRedirect()).open(Request(url, headers={"User-Agent": "UWMaster/1.0Beta (personal course monitor)"}), timeout=8) as response:
            final_url = response.url
            mime = response.headers.get_content_type()
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError("页面超过读取限制，请单独提供内容")
            if mime not in ("text/html", "text/plain"):
                return {**result, "message": "此来源需要另行读取文件内容（如 PDF）"}
            html = raw.decode(response.headers.get_content_charset() or "utf-8", errors="replace")
            if any(word in final_url.lower() for word in ("/login", "/signin", "/saml", "/sso")) or 'type="password"' in html.lower() or "type='password'" in html.lower():
                return {**result, "status": "login_required", "message": "需要登录，请在浏览器中打开来源；本次未核查该页面"}
            parser = PageText()
            parser.feed(html)
            text = "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())[:60000]
            if len(text) < 100:
                return {**result, "message": "未读到完整课程内容，可能需要登录或页面脚本"}
            return {"url": url, "final_url": final_url, "status": "read", "text": text, "message": "已读取页面文字，尚未核实或提取任务"}
    except Exception:
        return {**result, "message": "无法读取来源，可能需要登录、网络连接或单独读取文件"}


def start_retrieval(server, course_id):
    bundle = request_bundle(server, course_id)
    sources = list(dict.fromkeys(u for course in bundle["courses"] for u in course["sources"]))
    if not sources: raise ValueError("请先设置这门课的来源链接")
    with JOB_LOCK:
        if any(job["status"] == "running" for job in JOBS.values()):
            raise ValueError("已有检索正在进行，请等待完成")
        # Avoid retaining old source text indefinitely.
        JOBS.clear()
        token = uuid.uuid4().hex
        JOBS[token] = {"id": token, "status": "running", "total": len(sources), "completed": 0, "sources": [], "started_at": server.iso_now()}

    def run():
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                futures = [pool.submit(retrieve_source, url) for url in sources]
                for future in concurrent.futures.as_completed(futures):
                    result = future.result()
                    with JOB_LOCK:
                        JOBS[token]["sources"].append(result)
                        JOBS[token]["completed"] += 1
            with JOB_LOCK:
                JOBS[token].update(status="finished", finished_at=server.iso_now(), request=bundle)
        except Exception:
            with JOB_LOCK: JOBS[token].update(status="failed", message="检索中断，请重试")
    threading.Thread(target=run, daemon=True).start()
    return {"id": token, "status": "running"}


def retrieval_status(token):
    with JOB_LOCK:
        if token not in JOBS: raise ValueError("检索记录已失效，请重新检索")
        return copy.deepcopy(JOBS[token])


COMMON_RULES = "标题保持简短；具体动作、分值、权重和证据放详情。只纳入计分任务、CR/NC 必做要求及必须完成的课前材料。不得猜测时间或分值；个人课前目标与平台截止分开记录。沿用已有任务 ID，用户完成状态和备注由本地保存。"


def defaults(snapshot, project_rules):
    return {
        "schema_version": 1,
        "courses": [{
            "course_id": c["id"], "requirements": c.get("policy", ""),
            "sources": list(dict.fromkeys(u for u in [c.get("url"), c.get("canvas_url"), *[x.get("url") for x in c.get("coverage", [])]] if u)),
        } for c in snapshot.get("courses", [])],
        "common_rules": COMMON_RULES,
        "project_rules": project_rules,
    }


def load_settings(server):
    snapshot = server.source_snapshot() or {}
    rules = (server.ROOT / "TASK_RULES.md").read_text(encoding="utf-8")
    result = defaults(snapshot, rules)
    saved = server.read_json(server.DATA / "retrieval_settings.json", {})
    by_id = {c["course_id"]: c for c in saved.get("courses", [])}
    for course in result["courses"]:
        if course["course_id"] in by_id:
            course.update(by_id[course["course_id"]])
    return result


def validate_settings(body, snapshot):
    from urllib.parse import urlparse
    courses = body.get("courses")
    ids = {c["id"] for c in snapshot.get("courses", [])}
    if not isinstance(courses, list) or len(courses) != len(ids):
        raise ValueError("请为当前每门课程保留一份检索要求")
    result, seen = [], set()
    for c in courses:
        if not isinstance(c, dict) or c.get("course_id") not in ids or c["course_id"] in seen:
            raise ValueError("课程检索要求重复或引用了未知课程")
        requirements, sources = c.get("requirements"), c.get("sources")
        if not isinstance(requirements, str) or len(requirements) > 12000:
            raise ValueError("单门课程要求最多 12000 字符")
        if not isinstance(sources, list) or len(sources) > 30:
            raise ValueError("单门课程最多设置 30 个来源")
        for url in sources:
            if not isinstance(url, str) or len(url) > 2000:
                raise ValueError("来源链接无效")
            parsed = urlparse(url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("来源必须是 HTTPS 网页链接，不包含账号或密码")
        seen.add(c["course_id"])
        result.append({"course_id": c["course_id"], "requirements": requirements, "sources": list(dict.fromkeys(sources))})
    return {"schema_version": 1, "courses": result}


def digest(snapshot):
    return hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def task_changes(before, after):
    old = {t["id"]: t for t in before.get("tasks", [])}
    changes = []
    for task in after.get("tasks", []):
        previous = old.get(task["id"])
        fields = [k for k in sorted(set(task) | set(previous or {})) if not k.startswith("user_") and k != "checked_at" and (previous or {}).get(k) != task.get(k)]
        if previous is None or fields:
            changes.append({"type": "added" if previous is None else "changed", "task_id": task["id"], "course_id": task["course_id"], "title": task["title"], "fields": fields, "before": previous, "after": task})
    return changes


def prepare_preview(server, incoming):
    incoming = copy.deepcopy(server.validate_snapshot(incoming))
    current = server.source_snapshot()
    if incoming["term"]["id"] != current["term"]["id"]:
        raise ValueError("检索更新必须属于当前学期；换学期请使用原导入功能")
    if {c["id"] for c in incoming["courses"]} != {c["id"] for c in current["courses"]}:
        raise ValueError("检索更新须保留当前课程；新增或移除课程请使用原导入功能")
    for task in incoming["tasks"]:
        task.pop("user_completed", None)
        task.pop("user_note", None)
    merged = server.merge_snapshot(current, incoming)
    # Retrieval updates only task evidence. Preserve course/term/automation metadata.
    candidate = copy.deepcopy(current)
    candidate["tasks"] = merged["tasks"]
    changes = task_changes(current, candidate)
    token = uuid.uuid4().hex
    draft = {"id": token, "created_at": server.iso_now(), "base_digest": digest(current), "snapshot": candidate, "changes": changes}
    server.atomic_write(server.DATA / "retrieval_preview.json", draft)
    return {"id": token, "created_at": draft["created_at"], "changes": changes, "retained": len(current["tasks"]) - len({x["task_id"] for x in changes if x["type"] == "changed"}), "count": len(changes)}


def apply_preview(server, token):
    draft = server.read_json(server.DATA / "retrieval_preview.json", None)
    if not draft or token != draft.get("id"):
        raise ValueError("更新预览不存在或已失效，请重新预览")
    current = server.source_snapshot()
    if draft["base_digest"] != digest(current):
        raise ValueError("课程数据在预览后发生变化，请重新预览，避免覆盖其他更新")
    candidate = server.validate_snapshot(draft["snapshot"])
    changes = draft["changes"]
    if changes:
        server.atomic_write(server.SNAPSHOT, candidate)
        history = [{"at": server.iso_now(), "type": c["type"], "task_id": c["task_id"], "message": ("新增任务：" if c["type"] == "added" else "更新任务：") + c["title"]} for c in changes]
        server.atomic_write(server.HISTORY, (history + server.read_json(server.HISTORY, []))[:500])
    server.atomic_write(server.DATA / "retrieval_preview.json", {})
    return {"ok": True, "count": len(changes)}


def request_bundle(server, course_id):
    settings = load_settings(server)
    snapshot = server.source_snapshot()
    for task in snapshot.get("tasks", []):
        task.pop("user_completed", None)
        task.pop("user_note", None)
    ids = {c["id"] for c in snapshot["courses"]}
    if course_id != "all" and course_id not in ids:
        raise ValueError("课程不存在")
    selected = settings["courses"] if course_id == "all" else [c for c in settings["courses"] if c["course_id"] == course_id]
    return {"generated_at": server.iso_now(), "term": snapshot["term"], "common_rules": settings["common_rules"], "project_rules": settings["project_rules"], "courses": selected,
            "current_snapshot": snapshot,
            "output_requirements": "返回 schema_version: 1 的课程快照；沿用现有 task ID，仅新增或修改有来源证据的任务。不能替用户提交课业。访问失败须报告，不能声称完成核查。"}
