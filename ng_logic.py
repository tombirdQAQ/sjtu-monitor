"""ng 原生客户端共用的展示逻辑(纯函数,不联网、不写盘)。

Tauri 版把这些规则放在前端 courseLogic.ts;ng 的 macOS/Windows 两个原生客户端
不再各自重写,统一由 ng_service 通过 RPC 提供。冲突判定直接复用 timetable,
与 monitor.conflict_marks 是同一套实现。
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable

import timetable

# ---------------------------------------------------------------- 时间冲突 ---


def chosen_label(course: dict[str, Any]) -> str:
    title = str(course.get("title") or course.get("jxb_id") or "")
    class_name = course.get("class_name")
    return f"{title} - {class_name}" if class_name else title


def _schedule(course: dict[str, Any] | None) -> str | None:
    if not course:
        return None
    if course.get("sksj"):
        return str(course["sksj"])
    lines = course.get("schedule") or []
    return "\n".join(lines) or None


def _chosen_outside(group_ids: Iterable[str], choosed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """本组外、占用时段的已选课程(本组已选即将被换掉,不参与比较)。"""
    ids = set(group_ids)
    return [
        course for course in choosed
        if course.get("jxb_id") not in ids and not timetable.is_unscheduled(course.get("sksj"))
    ]


def _mark_against(schedule: str | None, others: list[dict[str, Any]]) -> dict[str, Any] | None:
    unknown = False
    for other in others:
        verdict = timetable.conflicts(schedule, other.get("sksj"))
        if verdict is None:
            unknown = True
            continue
        if verdict:
            return {
                "status": "conflict",
                "with": chosen_label(other),
                "detail": timetable.describe_conflict(schedule, other.get("sksj")),
            }
    return {"status": "unknown"} if unknown else None


def group_conflict_marks(
    priority: list[str],
    courses_by_id: dict[str, dict[str, Any]],
    choosed: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """与 monitor.conflict_marks 同一规则:可能被选择的课程(高于组内最高已选;组内
    无已选则整组)若与本组外已选课程时间冲突或无法判断,按规则不会被选择。"""
    chosen_ids = {course.get("jxb_id") for course in choosed}
    held_index = next((i for i, jxb_id in enumerate(priority) if jxb_id in chosen_ids), -1)
    candidates = priority if held_index < 0 else priority[:held_index]
    others = _chosen_outside(priority, choosed)
    marks: dict[str, dict[str, Any]] = {}
    if not others:
        return marks
    for jxb_id in candidates:
        mark = _mark_against(_schedule(courses_by_id.get(jxb_id)), others)
        if mark:
            marks[jxb_id] = mark
    return marks


def conflict_warning(
    added_ids: list[str],
    target_priority: list[str],
    courses_by_id: dict[str, dict[str, Any]],
    choosed: list[dict[str, Any]],
) -> str | None:
    """往方案加入课程时的冲突提示;冲突只警告,不禁止加入。"""
    chosen_ids = {course.get("jxb_id") for course in choosed}
    others = _chosen_outside([*target_priority, *added_ids], choosed)
    conflicts: list[str] = []
    unknowns: list[str] = []
    for added_id in added_ids:
        if added_id in chosen_ids:
            continue
        added = courses_by_id.get(added_id)
        mark = _mark_against(_schedule(added), others)
        title = (added or {}).get("title") or added_id
        if mark and mark["status"] == "conflict":
            conflicts.append(f"{title} 与已选 {mark['with']}　{mark['detail']}")
        elif mark and mark["status"] == "unknown":
            unknowns.append(title)
    if not conflicts and not unknowns:
        return None
    lines: list[str] = []
    if conflicts:
        lines.append("与本组外已选课程时间冲突，按规则不会被选择：")
        lines.extend(f"　{line}" for line in conflicts)
    if unknowns:
        lines.append("缺少时间数据，无法判断是否冲突，按规则不会被选择：")
        lines.extend(f"　{line}" for line in unknowns)
    lines.append("已加入方案，可继续保存。")
    return "\n".join(lines)


def merge_priority_ids(existing: list[str], added: list[str], chosen_ids: set[str]) -> list[str]:
    """新目标插在已选之前;已选班始终在末尾。"""
    chosen = [jxb_id for jxb_id in existing if jxb_id in chosen_ids]
    targets = [jxb_id for jxb_id in existing if jxb_id not in chosen_ids]
    for jxb_id in added:
        if jxb_id in targets or jxb_id in chosen:
            continue
        (chosen if jxb_id in chosen_ids else targets).append(jxb_id)
    return targets + chosen


# ---------------------------------------------------------------- 日志解析 ---

_LEVEL_TOKENS = {
    "DEBUG": "debug", "INFO": "info", "WARN": "warn", "WARNING": "warn",
    "ERROR": "error", "CRITICAL": "error",
}

_CHANGE_FIELD_LABELS = {
    "yxzrs": "已选", "xzzrs": "选中", "cxrs": "抽选人数", "jxbrs": "班人数",
    "jxbxzrs": "班选中", "syddrs": "剩余", "jxbrl": "容量", "yl": "总容量",
    "krrl": "可容", "cxrl": "抽选容量",
}

_STAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})(?:[,.]\d+)?\s+(.*)$", re.S)
_LOGGING_RE = re.compile(r"^(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL)\s+(?:\[([^\]]+)\]\s*)?(.*)$", re.S)
_EXIT_RE = re.compile(r"^exit=(.+)$")


def _format_change_record(record: dict[str, Any]) -> tuple[str, str]:
    label = f"{record.get('jxbmc') or ''} {record.get('kcmc') or ''}".strip()
    kind = str(record.get("kind") or "")
    if kind == "spot_open":
        return "warn", f"🔥 [有空位] {label} — {record.get('msg') or ''}"
    if kind == "swap_result":
        if record.get("ok"):
            return "info", f"✅ [换课成功] {label} 已抢到"
        status = str(record.get("status") or "")
        if status == "FATAL_LOST":
            return "error", f"❌ [换课致命错误] {label} — 旧课退了选不回，需人工处理"
        return "error", f"⚠️ [换课失败] {label} — {status}"
    if kind == "added":
        return "info", f"[新增] {label}"
    if kind == "removed":
        return "info", f"[移除] {label}"
    if kind == "conflict_skipped":
        return "warn", (
            f"[跳过换课·时间冲突] {label} — 与「{record.get('conflict_group') or '?'}」组冲突: "
            f"{record.get('detail') or ''}"
        )
    if kind == "schedule_unknown_skip":
        return "warn", f"[跳过换课·时间未知] {label} — 无法确认冲突，保守跳过"
    changes = record.get("changes")
    if isinstance(changes, dict):
        parts = []
        for field, pair in changes.items():
            before, after = (list(pair) + [None, None])[:2] if isinstance(pair, (list, tuple)) else (None, None)
            parts.append(f"{_CHANGE_FIELD_LABELS.get(field, field)} {before}→{after}")
        return "info", f"[变动] {label} {', '.join(parts)}"
    return "info", (f"[{kind}] " if kind else "") + label


def _infer_level(text: str) -> str:
    if text.startswith("$ "):
        return "debug"
    exit_match = _EXIT_RE.match(text)
    if exit_match:
        code = exit_match.group(1)
        return "info" if code == "0" else ("warn" if code == "-" else "error")
    if "Traceback (most recent call last)" in text:
        return "error"
    if re.search(r"\b(ERROR|CRITICAL|FAILED)\b", text) or "失败" in text or "错误" in text:
        return "error"
    if re.search(r"\bWARN(ING)?\b", text) or "警告" in text:
        return "warn"
    return "info"


def parse_log_line(source: str, text: str, fallback_time: str = "") -> dict[str, str]:
    line = text.strip()
    stamped = _STAMP_RE.match(line)
    time = stamped.group(2) if stamped else fallback_time
    rest = stamped.group(3) if stamped else line
    logging_match = _LOGGING_RE.match(rest)
    if logging_match:
        return {
            "time": time,
            "level": _LEVEL_TOKENS[logging_match.group(1)],
            "source": logging_match.group(2) or source,
            "message": logging_match.group(3) or rest,
        }
    if rest.startswith("{"):
        try:
            record = json.loads(rest)
        except json.JSONDecodeError:
            record = None
        if isinstance(record, dict):
            level, message = _format_change_record(record)
            return {"time": time, "level": level, "source": source, "message": message}
    return {"time": time, "level": _infer_level(rest), "source": source, "message": rest}


# ------------------------------------------------------- 抓取进程失败提示 ---

BOOTSTRAP_RESULT_PREFIX = "[bootstrap-result] "

_FAILURE_TITLES = {
    "term_mismatch": "学期与教务网站不一致",
    "closed": "教务网站选课未开放",
    "empty": "没有获取到课程",
    "login": "登录失败",
    "session": "登录会话被顶掉",
    "network": "无法连接教务网站",
}


def parse_bootstrap_result(line: str) -> dict[str, Any] | None:
    index = line.find(BOOTSTRAP_RESULT_PREFIX)
    if index < 0:
        return None
    try:
        value = json.loads(line[index + len(BOOTSTRAP_RESULT_PREFIX):])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) and isinstance(value.get("ok"), bool) else None


def bootstrap_failure_notice(
    result: dict[str, Any] | None, code: int | None, action: str = "获取全量课程",
) -> dict[str, str]:
    if result and not result.get("ok"):
        return {
            "title": _FAILURE_TITLES.get(str(result.get("reason") or ""), f"{action}失败"),
            "message": result.get("message") or f"{action}失败，请查看日志页。",
        }
    return {
        "title": f"{action}失败",
        "message": (
            f"进程异常退出（exit={'-' if code is None else code}）。可能不在选课期间、"
            "所选学期与教务网站不一致，或教务网站暂时不可达，请查看日志页了解详情。"
        ),
    }
