"""Evidence-backed, field-level three-way merge; never writes personal state."""
import copy
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

RUNTIME = Path(__file__).resolve().parent / "work/runtime-packages"
if RUNTIME.is_dir(): sys.path.insert(0, str(RUNTIME))

FIELDS = {"title", "original_title", "due", "end", "available_from", "kind", "description",
          "points", "weight", "grade_impact", "certainty", "time_basis", "platform_due_label",
          "source_status", "submission_status", "completion_status", "grading_status", "lifecycle"}
KINDS = {"homework", "quiz", "exam", "project", "participation", "class", "extra_credit", "preparation"}


def normalized(value):
    return re.sub(r"\s+", " ", str(value)).strip().casefold()


def valid_field(name, value):
    if name not in FIELDS:
        return False
    if value is None:
        return name not in {"title", "kind", "description", "certainty", "lifecycle"}
    if name in {"due", "end", "available_from"}:
        if not isinstance(value, str): return False
        try:
            if len(value) == 10:
                dt.date.fromisoformat(value)
            else:
                if dt.datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None: return False
            return True
        except ValueError: return False
    if name in {"points", "weight"}:
        return isinstance(value, (str, int, float)) and not isinstance(value, bool)
    if name == "kind": return value in KINDS
    if name == "certainty": return value in {"verified", "tentative", "needs_confirmation"}
    if name == "submission_status": return value in {"submitted", "not_submitted", "unknown"}
    if name == "completion_status": return value in {"completed", "not_completed", "unknown"}
    if name == "grading_status": return value in {"graded", "ungraded", "unknown"}
    if name == "lifecycle": return value in {"active", "cancelled", "excluded"}
    if name == "source_status": return value in {"completed", "scored", "published", "pending", "unknown", "not_completed"}
    return isinstance(value, str) and len(value) <= 12000 and (name != "title" or 0 < len(value.strip()) <= 160)


def in_future(value, cutoff):
    if not value: return True
    if len(value) == 10:
        return dt.date.fromisoformat(value) >= cutoff.astimezone(ZoneInfo("America/Los_Angeles")).date()
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")) >= cutoff


def reconcile(base, current, result, evidence, selected, cutoff, states=None):
    """Return a candidate and report. Missing fields/tasks are not deletions."""
    if base["term"]["id"] != current["term"]["id"]:
        raise ValueError("检索期间学期已切换，请重新检索。")
    candidate = copy.deepcopy(current)
    old = {t["id"]: t for t in base["tasks"]}
    tasks = {t["id"]: t for t in candidate["tasks"]}
    sources = {e["url"]: e for e in evidence if e.get("status") == "read"}
    report = {"changes": [], "conflicts": [], "notices": [], "rejected": []}
    proposals, observed, blocked = {}, set(), set()
    def issue(kind, task_id, field, message, **extra):
        key = hashlib.sha256(json.dumps([kind, task_id, field, message, extra], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]
        report[kind].append({"id": key, "task_id": task_id, "field": field, "message": message, **extra})
    for observation in result.get("observations", []):
        tid, course, url = observation.get("task_id"), observation.get("course_id"), observation.get("source_url")
        quote = observation.get("evidence", "")
        if course not in selected or url not in sources or not isinstance(quote, str) or len(normalized(quote)) < 8 or normalized(quote) not in normalized(sources[url].get("text", "")):
            issue("rejected", tid, None, "缺少本次已读取来源中的有效原文证据，未应用。")
            continue
        fields = {}
        for field in observation.get("fields", []):
            name = field.get("name")
            try: value = json.loads(field.get("value_json", ""))
            except (ValueError, TypeError):
                issue("rejected", tid, name, "字段不是有效 JSON，未应用。")
                continue
            if not valid_field(name, value):
                issue("rejected", tid, name, "字段或日期格式无效，未应用。")
                continue
            # Unknown or omitted is never evidence for clearing an established fact.
            if value == "unknown" or value is None and not field.get("explicit_clear"):
                continue
            fields[name] = value
        if not tid:
            key = observation.get("source_key")
            if not isinstance(key, str) or not key.strip():
                issue("rejected", None, None, "新增任务缺少稳定来源标识。", source_url=url)
                continue
            tid = "source-" + hashlib.sha256((base["term"]["id"] + "|" + course + "|" + key).encode()).hexdigest()[:24]
            similar = [t for t in tasks.values() if t["course_id"] == course and normalized(t["title"]) == normalized(fields.get("title", "")) and t["id"] != tid]
            if similar:
                issue("conflicts", tid, "identity", "可能与已有任务重复，暂缓新增，请核对来源身份。", related_ids=[t["id"] for t in similar], source_url=url)
                continue
        previous = tasks.get(tid)
        if previous and (previous["course_id"] != course or previous.get("manual")):
            issue("rejected", tid, None, "不能更改课程归属或覆盖手动任务。")
            continue
        if tid not in old and tid not in tasks and observation.get("task_id"):
            issue("rejected", tid, None, "已有任务 ID 未在当前快照中找到；新增任务请使用来源标识。")
            continue
        blockers = observation.get("blockers", [])
        if course == "cse123" and fields.get("kind") == "class" and "lecture" in normalized(fields.get("title", previous.get("title", "") if previous else "")):
            blockers = [*blockers, "现有规则明确排除 CSE 123 lecture，不能自动纳入。"]
        if blockers:
            blocked.add(tid)
            for message in blockers:
                issue("conflicts", tid, "rules", str(message), source_url=url, evidence=quote)
            continue
        if not previous and (not fields.get("title") or "due" not in fields or not fields.get("kind")):
            issue("rejected", tid, None, "新增任务缺少标题、截止（可明确未知）或分类。")
            # Unknown due is allowed when the AI explicitly provides null.
            if fields.get("title") and fields.get("kind") and any(f.get("name") == "due" and f.get("value_json") == "null" for f in observation.get("fields", [])):
                fields["due"] = None
                report["rejected"].pop()
            else: continue
        if not previous and not in_future(fields.get("due"), cutoff):
            issue("rejected", tid, "due", "新增任务在本次未来检索范围之外。")
            continue
        observed.add(tid)
        proposals.setdefault(tid, {"course_id": course, "source_url": url, "source_key": observation.get("source_key"), "fields": {}})
        for name, value in fields.items():
            proposals[tid]["fields"].setdefault(name, []).append({"value": value, "source_url": url, "evidence": quote})
    for tid, proposal in proposals.items():
        if tid in blocked: continue
        before = copy.deepcopy(tasks.get(tid))
        task = copy.deepcopy(before) if before else {"id": tid, "course_id": proposal["course_id"], "source_url": proposal["source_url"], "source_key": proposal["source_key"]}
        for name, offers in proposal["fields"].items():
            distinct = {json.dumps(o["value"], sort_keys=True, ensure_ascii=False) for o in offers}
            if len(distinct) > 1:
                issue("conflicts", tid, name, "本次来源对同一字段给出不同值，保留原值。", current=(before or {}).get(name), original_certainty=(before or {}).get("certainty"), offers=offers)
                continue
            value = offers[0]["value"]
            # New fact differs from both baseline and a concurrently updated field.
            if before and before.get(name) != old.get(tid, {}).get(name) and before.get(name) != value:
                issue("conflicts", tid, name, "检索期间此字段已被其他更新修改，保留当前值。", current=before.get(name), original_certainty=before.get("certainty"), offers=offers)
                continue
            task[name] = value
            task.setdefault("field_evidence", {})[name] = {**offers[0], "checked_at": cutoff.isoformat()}
        if not before and (not task.get("title") or "due" not in task or not task.get("kind")):
            issue("rejected", tid, None, "新增任务关键字段有冲突，未创建。")
            continue
        task["checked_at"] = cutoff.isoformat()
        saved = (states or {}).get(tid, {})
        if saved.get("completed") and (task.get("submission_status") == "not_submitted" or task.get("completion_status") == "not_completed" or task.get("source_status") == "not_completed"):
            issue("notices", tid, "completion", "你已标记完成，但平台明确显示未提交或未完成；个人完成记录已保留。", source_url=proposal["source_url"])
        if before and saved.get("completed") and task.get("description") != before.get("description"):
            issue("notices", tid, "requirements", "已完成任务的内容发生变化，请复核是否有新增要求；个人完成记录已保留。")
        fields = [k for k in FIELDS if (before or {}).get(k) != task.get(k)]
        if before is None or fields:
            report["changes"].append({"type": "added" if before is None else "changed", "task_id": tid,
                                      "title": task["title"], "fields": sorted(fields), "before": before, "after": copy.deepcopy(task)})
        tasks[tid] = task
    # A stale source value with conflict remains visible as uncertain, without changing user state.
    for conflict in report["conflicts"]:
        if conflict["task_id"] in tasks:
            task = tasks[conflict["task_id"]]
            task["needs_review"] = True
            if conflict["field"] in {"due", "end"}: task["certainty"] = "needs_confirmation"
    candidate["tasks"] = list(tasks.values())
    for change in report["changes"]:
        change["after"] = copy.deepcopy(tasks[change["task_id"]])
    report["observed_ids"] = sorted(observed)
    return candidate, report
