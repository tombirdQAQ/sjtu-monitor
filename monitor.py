"""SJTU 选课监控主程序。

用法:
  python monitor.py            # 长跑,持续轮询
  python monitor.py --once     # 拉一次就退
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

import bootstrap
import config
import notifier
import swap as swap_mod
import timetable
import zzxk
from login import LoginError, ensure_session

log = logging.getLogger("monitor")

# 选课开放前所有人数/容量字段都是 '0',开放后学校实际填的是哪个不确定 ——
# 把所有相关字段都纳入 diff,任何一个变了都通知。
DIFF_FIELDS = (
    "yxzrs",    # 已选中人数 (最可能的"已选")
    "xzzrs",    # 选中人数
    "cxrs",     # 抽选人数
    "jxbrs",    # 教学班人数
    "jxbxzrs",  # 教学班选中人数
    "syddrs",   # 剩余可选人数
    "jxbrl",    # 教学班容量 (最可能的"容量")
    "yl",       # 容量
    "krrl",     # 可容容量
    "cxrl",     # 抽选容量
)


class SessionExpired(RuntimeError):
    pass


_HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": config.REFERER,
    "Origin": "https://i.sjtu.edu.cn",
    "User-Agent": config.USER_AGENT,
}


def _fetch_one_course(session: requests.Session, kch: str) -> list[dict]:
    """查询单门课的全部教学班。普通课/体育课走不同接口,由 KCH_QUERIES 决定。"""
    qp = config.build_query_payload(kch)
    if qp is None:
        log.warning("kch=%s 没在 KCH_QUERIES 里,跳过", kch)
        return []
    url, payload = qp
    r = session.post(
        url, data=payload, headers=_HEADERS,
        timeout=15, allow_redirects=False,
    )
    ct = r.headers.get("content-type", "")
    if r.status_code in (302, 401, 403) or "application/json" not in ct:
        raise SessionExpired(
            f"status={r.status_code} ct={ct} body={r.text[:120]}"
        )
    endpoint = config.KCH_QUERIES[kch]["endpoint"]
    return config.parse_class_list(endpoint, r.json())


def fetch_courses(session: requests.Session) -> tuple[list[dict], set[str]]:
    """对 KCH_QUERIES 里的每门课查一次,返回 (所有教学班, 本轮没拿到数据的课程号)。

    endpoint 路由(两个选课轮次课程不重叠、id 不通用,2026-07 实测):
      display / pe → tjxkbkk 补退选接口(原有路径,逐课查询)
      zzxk         → zzxkyzb 自主选课模块(zzxk.fetch_seats,按分类批量查询)

    接口偶尔会 200 返回空列表(服务端抖动/选课模块短暂关闭),这种"整门课一个班都
    没有"的结果不能当成真实数据:第二个返回值交给 run_once 兜底,避免残缺结果覆盖
    state.json 并误报教学班被删除。
    """
    all_classes: list[dict] = []
    seen: set[str] = set()
    counts: dict[str, int] = {kch: 0 for kch in config.KCH_QUERIES}
    zzxk_courses: dict[str, dict] = {}
    for kch, q in config.KCH_QUERIES.items():
        if q.get("endpoint") == "zzxk":
            zzxk_courses[kch] = q
            continue
        classes = _fetch_one_course(session, kch)
        for c in classes:
            jxb_id = c.get("jxb_id")
            if jxb_id and jxb_id not in seen:
                seen.add(jxb_id)
                all_classes.append(c)
        counts[kch] = len(classes)
        log.debug("kch=%s 拉到 %d 个教学班", kch, len(classes))
    if zzxk_courses:
        try:
            rows = zzxk.fetch_seats(session, zzxk_courses)
        except zzxk.SessionExpired as e:
            raise SessionExpired(str(e)) from e
        for jxb_id, c in rows.items():
            if jxb_id not in seen:
                seen.add(jxb_id)
                all_classes.append(c)
            counts[c.get("kch")] = counts.get(c.get("kch"), 0) + 1
        log.debug("zzxk %d 门课拉到 %d 个教学班", len(zzxk_courses), len(rows))
    missing = {kch for kch, n in counts.items() if not n}
    return all_classes, missing


def load_state() -> dict[str, dict]:
    if not config.STATE_FILE.exists():
        return {}
    try:
        return json.loads(config.STATE_FILE.read_text("utf-8"))
    except Exception as e:
        log.warning("state.json 损坏,重建: %s", e)
        return {}


def save_state(state: dict[str, dict]) -> None:
    tmp = config.STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), "utf-8")
    config.replace_atomic(tmp, config.STATE_FILE)


def _to_int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _has_spot(course: dict) -> bool | None:
    """jxbxzrs < jxbrl ⇒ 有空位。任一字段缺失/不可比 → None。"""
    sel = _to_int(course.get("jxbxzrs"))
    cap = _to_int(course.get("jxbrl"))
    if sel is None or cap is None or cap <= 0:
        return None
    return sel < cap


def _open_targets(
    current: dict[str, dict], watched: set[str]
) -> list[dict]:
    """构造当前确有空位的自动升级候选,不依赖空位是否刚刚出现。"""
    targets = []
    for jxb_id in watched:
        course = current.get(jxb_id)
        if course and _has_spot(course):
            targets.append({
                "kind": "spot_open",
                "jxb_id": jxb_id,
                "jxbmc": course.get("jxbmc"),
                "kcmc": course.get("kcmc"),
                "msg": f"有空位! {course.get('jxbxzrs')}/{course.get('jxbrl')}",
            })
    return targets


def _held_by_group(completed: set[str]) -> dict[str, str]:
    """根据初始配置和成功记录计算每组当前持有的最高优先级班。"""
    held = config.initial_held()
    for group, group_cfg in config.PRIORITY_GROUPS.items():
        completed_in_group = [
            jxb_id for jxb_id in group_cfg["priority"] if jxb_id in completed
        ]
        if completed_in_group:
            # priority 从高到低排列,取已完成目标中优先级最高的一项。
            held[group] = completed_in_group[0]
    return held


def _held_from_choosed(choosed_ids: set[str]) -> dict[str, str]:
    """按实际已选计算每组持有:组内已选中优先级最高的一项;组内无已选则不出现在结果里。

    取最高一项保证"不降级":即使组内还残留低优先级已选,也只把高优先级视为持有。
    """
    held: dict[str, str] = {}
    for group, group_cfg in config.PRIORITY_GROUPS.items():
        for jxb_id in group_cfg["priority"]:
            if jxb_id in choosed_ids:
                held[group] = jxb_id
                break
    return held


def _watched_ids(
    sw_state: dict | None = None, held: dict[str, str] | None = None,
) -> set[str]:
    """只返回各组当前持有班之前的目标(组内无持有则整组);致命失败组暂停监控。

    held 缺省时按旧推断(方案末项 + 换课成功记录)计算。
    """
    sw_state = _load_swap_state() if sw_state is None else sw_state
    if held is None:
        held = _held_by_group(set(sw_state.get("completed", [])))
    watched = config.watched_ids(held)
    for group in sw_state.get("fatal_groups", []):
        group_cfg = config.PRIORITY_GROUPS.get(group)
        if group_cfg:
            watched.difference_update(group_cfg["priority"])
    return watched


def diff(
    old: dict[str, dict],
    new: dict[str, dict],
    watched: set[str] | None = None,
) -> list[dict]:
    """只对当前优先级范围内的教学班产生通知;其他班存盘但不打扰。

    特别地:当 jxbxzrs < jxbrl(有空位) 且上一轮还是满的(或第一次见到)时,
    额外产生一条 kind='spot_open' 的紧急通知。
    """
    changes = []
    watched = _watched_ids() if watched is None else watched
    for jxb_id, course in new.items():
        if jxb_id not in watched:
            continue
        prev = old.get(jxb_id)

        # 1) 空位告警:上轮无 / 上轮满 → 这轮有空位
        now_open = _has_spot(course)
        was_open = _has_spot(prev) if prev else False
        if now_open and not was_open:
            sel = course.get("jxbxzrs")
            cap = course.get("jxbrl")
            changes.append({
                "kind": "spot_open",
                "jxb_id": jxb_id,
                "jxbmc": course.get("jxbmc"),
                "kcmc": course.get("kcmc"),
                "msg": f"有空位! {sel}/{cap}",
            })

        # 2) 常规 diff
        if prev is None:
            changes.append({"kind": "added", **course})
            continue
        field_diffs = {}
        for f in DIFF_FIELDS:
            if prev.get(f) != course.get(f):
                field_diffs[f] = (prev.get(f), course.get(f))
        if field_diffs:
            changes.append({
                "kind": "changed",
                "jxbmc": course.get("jxbmc"),
                "kcmc": course.get("kcmc"),
                "changes": field_diffs,
            })

    for jxb_id, course in old.items():
        if jxb_id not in watched:
            continue
        if jxb_id not in new:
            changes.append({"kind": "removed", **course})
    return changes


def append_log(changes: list[dict]) -> None:
    ts = datetime.now().isoformat(timespec="seconds")
    with config.LOG_FILE.open("a", encoding="utf-8") as f:
        for c in changes:
            f.write(f"{ts} {json.dumps(c, ensure_ascii=False)}\n")


def _load_swap_state() -> dict:
    if not config.SWAP_STATE_FILE.exists():
        return {"completed": [], "fatal": [], "fatal_groups": []}
    try:
        return json.loads(config.SWAP_STATE_FILE.read_text("utf-8"))
    except Exception:
        return {"completed": [], "fatal": [], "fatal_groups": []}


def _save_swap_state(state: dict) -> None:
    tmp = config.SWAP_STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), "utf-8")
    config.replace_atomic(tmp, config.SWAP_STATE_FILE)


# === 实际已选课程 ===
# 每轮以服务器已选列表为准计算各组持有班,避免用户在网页上手动改课后监控端仍按旧推断操作。
# 抓取失败时沿用上一次成功的记录(自动换课成功后会立即改写该记录)并告警;
# 从未成功过则回退到"方案末项 + 换课成功记录"的旧推断。
# 记录存于 catalog.json 的 choosed,GUI 据此显示当前已选与冲突标记。

# 告警去重:长跑进程里连续失败只在开始失败和恢复时各通知一次。
_choosed_fetch_failing = False
_last_conflict_marks: dict[str, dict[str, dict]] | None = None


def fetch_choosed(session: requests.Session) -> list[dict] | None:
    """服务器上当前实际已选。

    两个模块的已选接口实测返回同一份全部已选(2026-09 联网验证):tjxkbkk 优先,
    失败或为空再试 zzxk。都失败/都为空返回 None(空列表无法与"学期参数不对"区分)。
    """
    for name, fetch in (("tjxkbkk", bootstrap.fetch_choosed),
                        ("zzxk", zzxk.fetch_choosed)):
        try:
            rows = [row for row in fetch(session) if row.get("jxb_id")]
        except Exception as e:
            log.warning("[已选] %s 已选接口查询失败: %s", name, e)
            continue
        if rows:
            return rows
        log.warning("[已选] %s 已选接口返回空列表", name)
    return None


def _slim_choosed(row: dict) -> dict:
    return bootstrap._slim_class(row, include_availability=False)


def load_saved_choosed() -> dict[str, dict] | None:
    """catalog.json 里上一次成功(或换课后改写)的已选记录;没有记录返回 None。"""
    try:
        catalog = json.loads(config.CATALOG_FILE.read_text("utf-8"))
    except Exception:
        return None
    rows = catalog.get("choosed") if isinstance(catalog, dict) else None
    if not isinstance(rows, list):
        return None
    saved = {
        row["jxb_id"]: row for row in rows
        if isinstance(row, dict) and row.get("jxb_id")
    }
    return saved or None


def save_choosed(choosed: dict[str, dict]) -> None:
    """只改写 catalog.json 的 choosed/choosed_at,其他分区原样保留。"""
    catalog: dict = {}
    if config.CATALOG_FILE.exists():
        try:
            catalog = json.loads(config.CATALOG_FILE.read_text("utf-8"))
        except Exception as e:
            log.warning("[已选] catalog.json 无法读取,不写入已选记录: %s", e)
            return
        if not isinstance(catalog, dict):
            log.warning("[已选] catalog.json 格式异常,不写入已选记录")
            return
    catalog["choosed"] = list(choosed.values())
    catalog["choosed_at"] = datetime.now().isoformat(timespec="seconds")
    tmp = config.CATALOG_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), "utf-8")
    config.replace_atomic(tmp, config.CATALOG_FILE)


def _course_label(row: dict) -> str:
    return f"{row.get('kcmc') or ''} {row.get('jxbmc') or row.get('jxb_id') or ''}".strip()


def resolve_choosed(session: requests.Session) -> tuple[dict[str, dict] | None, list[dict]]:
    """本轮使用的已选 {jxb_id: row} 及需要通知的记录。

    - 抓取成功:以实时结果为准,与上次记录不同则通知并存盘;
    - 抓取失败:沿用上次记录并告警;无记录返回 None(调用方回退旧推断)。
    """
    global _choosed_fetch_failing
    saved = load_saved_choosed()
    rows = fetch_choosed(session)
    notes: list[dict] = []
    if rows is not None:
        live = {row["jxb_id"]: _slim_choosed(row) for row in rows}
        if _choosed_fetch_failing:
            notes.append({"kind": "choosed_fetch_recovered", "count": len(live)})
        _choosed_fetch_failing = False
        if saved is not None and set(saved) != set(live):
            notes.append({
                "kind": "choosed_changed",
                "added": [_course_label(live[i]) for i in live if i not in saved],
                "removed": [_course_label(saved[i]) for i in saved if i not in live],
            })
        if saved != live:
            save_choosed(live)
        log.info("[已选] 实时已选 %d 门", len(live))
        return live, notes
    fallback = "saved" if saved is not None else "config"
    if fallback == "saved":
        log.warning("[已选] 抓取失败,沿用上次记录(%d 门)", len(saved))
    else:
        log.warning("[已选] 抓取失败且无历史记录,回退为方案末项 + 换课记录推断")
    if not _choosed_fetch_failing:
        notes.append({
            "kind": "choosed_fetch_failed",
            "fallback": fallback,
            "count": len(saved) if saved else 0,
        })
    _choosed_fetch_failing = True
    return saved, notes


def _conflict_with_choosed(
    current: dict[str, dict], group: str, target_id: str, choosed: dict[str, dict],
) -> tuple[dict | None, str | None, bool]:
    """目标与"本组外"全部实际已选课程的时间冲突判定。

    返回 (确定冲突的已选课程行或 None, 冲突时段描述, 是否存在无法判断的比较)。
    本组内的已选(即将被换掉的持有班)不参与比较;不排课/待定的已选课程不占时段,跳过。
    """
    group_ids = set(config.PRIORITY_GROUPS.get(group, {}).get("priority", []))
    target_sksj = current.get(target_id, {}).get("sksj")
    schedule_unknown = False
    for jxb_id, row in choosed.items():
        if jxb_id in group_ids or timetable.is_unscheduled(row.get("sksj")):
            continue
        verdict = timetable.conflicts(target_sksj, row.get("sksj"))
        if verdict is True:
            return row, timetable.describe_conflict(target_sksj, row.get("sksj")), schedule_unknown
        if verdict is None:
            schedule_unknown = True
    return None, None, schedule_unknown


def conflict_marks(
    current: dict[str, dict], watched: set[str], choosed: dict[str, dict],
) -> dict[str, dict[str, dict]]:
    """所有可能被选择的监控目标中,与本组外已选冲突(或无法判断)而不会被选择的课程,按组归集。"""
    marks: dict[str, dict[str, dict]] = {}
    for jxb_id in sorted(watched):
        group = config.find_group(jxb_id)
        if group is None or jxb_id in choosed:
            continue
        row, detail, unknown = _conflict_with_choosed(current, group, jxb_id, choosed)
        if row is not None:
            marks.setdefault(group, {})[jxb_id] = {
                "status": "conflict", "with": row["jxb_id"], "detail": detail,
            }
        elif unknown:
            marks.setdefault(group, {})[jxb_id] = {"status": "unknown"}
    return marks


def _log_conflict_marks(
    marks: dict[str, dict[str, dict]], current: dict[str, dict], choosed: dict[str, dict],
) -> None:
    global _last_conflict_marks
    if marks == _last_conflict_marks:
        return
    _last_conflict_marks = marks
    if not marks:
        log.info("[冲突] 监控目标与本组外已选课程均无时间冲突")
        return
    for group, items in marks.items():
        for jxb_id, mark in items.items():
            label = _course_label(current.get(jxb_id, {"jxb_id": jxb_id}))
            if mark["status"] == "conflict":
                other = _course_label(choosed.get(mark["with"], {"jxb_id": mark["with"]}))
                log.info("[冲突] %s 组: %s 与已选 %s 冲突(%s),不会被选择",
                         group, label, other, mark["detail"])
            else:
                log.info("[冲突] %s 组: %s 时间数据不全,无法判断冲突,不会被选择",
                         group, label)


def _conflict_with_other_groups(
    current: dict[str, dict], group: str, target_id: str, held: dict[str, str],
) -> tuple[str | None, str | None, bool]:
    """目标候选与其他组当前持有课程的时间冲突判定。

    返回 (确定冲突的组名或 None, 冲突时段描述, 是否存在因数据缺失而无法判断的组)。
    只与"当前持有"比较——冲突判定必须动态、实时:今天冲突不代表以后也冲突,
    因为别组自己换课后 held 会变,下一轮重新判断即可。
    """
    target_sksj = current.get(target_id, {}).get("sksj")
    schedule_unknown = False
    for other_group in config.PRIORITY_GROUPS:
        if other_group == group:
            continue
        other_held_id = held.get(other_group)
        if not other_held_id:
            continue
        other_sksj = current.get(other_held_id, {}).get("sksj")
        verdict = timetable.conflicts(target_sksj, other_sksj)
        if verdict is True:
            return other_group, timetable.describe_conflict(target_sksj, other_sksj), schedule_unknown
        if verdict is None:
            schedule_unknown = True
    return None, None, schedule_unknown


def maybe_auto_swap(
    session: requests.Session,
    spot_open_changes: list[dict],
    current: dict[str, dict],
    choosed: dict[str, dict] | None = None,
) -> list[dict]:
    """每组按优先级从高到低,对第一个不冲突的空位目标执行一次升级。

    choosed 为本轮使用的已选 {jxb_id: row}(实时结果或沿用的记录):
      - 持有班 = 组内已选中优先级最高的一项;组内无已选时直接选课,不需退课;
      - 冲突与本组外全部已选课程比较,冲突或无法判断的目标不会被选择;
      - 换课结果就地写回 choosed,调用方据此存盘。
    choosed=None(从未成功获取已选)时回退旧推断:持有 = 方案末项 + 换课成功记录,
    冲突只与其他组持有班比较,组内无持有则不换课。

    返回 swap 操作的结果列表,可作为额外通知项。
    """
    if not config.AUTO_SWAP:
        return []
    sw_state = _load_swap_state()
    completed: set[str] = set(sw_state.get("completed", []))
    fatal: set[str] = set(sw_state.get("fatal", []))
    fatal_groups: set[str] = set(sw_state.get("fatal_groups", []))
    if choosed is not None:
        held = _held_from_choosed(set(choosed))
    else:
        held = _held_by_group(completed)
    results = []

    # 同组可能同时有多个班空出。先分组,再按优先级从高到低逐个判定冲突。
    candidates: dict[str, list[dict]] = {}
    for c in spot_open_changes:
        target_id = c.get("jxb_id")
        if not target_id:
            continue
        group = config.find_group(target_id)
        if group is None:
            log.warning("[swap] %s 不属于任何优先级组,跳过", target_id)
            continue
        if group in fatal_groups:
            log.warning("[swap] %s 组之前发生 FATAL,人工处理前暂停", group)
            continue
        ids = config.PRIORITY_GROUPS[group]["priority"]
        current_held = held.get(group)
        if current_held in ids:
            if ids.index(target_id) >= ids.index(current_held):
                log.info("[swap] %s 不高于当前持有 %s,跳过", target_id, current_held)
                continue
        elif choosed is None:
            log.info("[swap] %s 组无法确定当前持有,跳过 %s", group, target_id)
            continue
        candidates.setdefault(group, []).append(c)

    for group, group_candidates in candidates.items():
        group_cfg = config.PRIORITY_GROUPS[group]
        ids = group_cfg["priority"]
        for c in sorted(group_candidates, key=lambda item: ids.index(item["jxb_id"])):
            target_id = c["jxb_id"]
            if choosed is not None:
                conflict_row, conflict_detail, schedule_unknown = _conflict_with_choosed(
                    current, group, target_id, choosed
                )
                conflict = None if conflict_row is None else {
                    "conflict_group": config.find_group(conflict_row["jxb_id"]),
                    "conflict_course": _course_label(conflict_row),
                }
            else:
                conflict_group, conflict_detail, schedule_unknown = _conflict_with_other_groups(
                    current, group, target_id, held
                )
                conflict = None if conflict_group is None else {"conflict_group": conflict_group}
            if conflict:
                log.info("[swap] %s 与已选课程时间冲突(%s),不会被选择: %s",
                         target_id, conflict_detail, conflict)
                results.append({
                    "kind": "conflict_skipped",
                    "jxbmc": c.get("jxbmc"), "kcmc": c.get("kcmc"),
                    "group": group, "target": target_id,
                    **conflict, "detail": conflict_detail,
                })
                continue
            if schedule_unknown:
                log.info("[swap] %s 与已选课程的时间数据不全,保守跳过", target_id)
                results.append({
                    "kind": "schedule_unknown_skip",
                    "jxbmc": c.get("jxbmc"), "kcmc": c.get("kcmc"),
                    "group": group, "target": target_id,
                })
                continue

            drop_id = held.get(group)
            is_pe = group_cfg.get("is_pe", False)
            log.info("[swap] 触发: group=%s target=%s drop=%s is_pe=%s dry=%s",
                     group, target_id, drop_id, is_pe, config.AUTO_SWAP_DRY_RUN)
            if drop_id is None:
                # 组内无已选:直接选课,没有退课环节,失败也不会落空。
                ok, body = swap_mod.select_course(
                    session, target_id, is_pe=is_pe, dry_run=config.AUTO_SWAP_DRY_RUN,
                )
                status = "ok" if ok else "select_failed"
                if not ok:
                    log.warning("[swap] 直接选课失败: %s", body)
            else:
                ok, status = swap_mod.drop_then_select(
                    session,
                    drop_jxb_id=drop_id,
                    select_jxb_id=target_id,
                    is_pe=is_pe,
                    dry_run=config.AUTO_SWAP_DRY_RUN,
                )
            results.append({
                "kind": "swap_result",
                "jxbmc": c.get("jxbmc"),
                "kcmc": c.get("kcmc"),
                "ok": ok,
                "status": status,
                "dry_run": config.AUTO_SWAP_DRY_RUN,
                "group": group,
                "target": target_id,
                "drop": drop_id,
            })
            if ok and not config.AUTO_SWAP_DRY_RUN:
                completed.add(target_id)
                held[group] = target_id
                if choosed is not None:
                    if drop_id:
                        choosed.pop(drop_id, None)
                    choosed[target_id] = _slim_choosed(
                        {**current.get(target_id, {}), "jxb_id": target_id}
                    )
            elif status == "FATAL_LOST":
                fatal.add(target_id)
                fatal_groups.add(group)
                if choosed is not None and drop_id:
                    choosed.pop(drop_id, None)
            # 每组每轮最多执行一次换课。
            break
    sw_state["completed"] = sorted(completed)
    sw_state["fatal"] = sorted(fatal)
    sw_state["fatal_groups"] = sorted(fatal_groups)
    _save_swap_state(sw_state)
    return results


def _carry_over_missing(
    state: dict[str, dict], current: dict[str, dict], missing: set[str]
) -> dict[str, dict]:
    """把本轮没查到数据的课程沿用上一轮的教学班,返回补齐后的快照。

    只在"整门课一个班都没返回"时兜底(接口抖动),单个班消失仍按真实变更处理。
    """
    if not missing or not state:
        return current
    carried = {
        jxb_id: row for jxb_id, row in state.items()
        if row.get("kch") in missing and jxb_id not in current
    }
    if carried:
        log.warning("课程 %s 本轮无数据,沿用上一轮的 %d 个教学班(不覆盖快照)",
                    ",".join(sorted(missing)), len(carried))
    return {**current, **carried}


def run_once(session: requests.Session, state: dict[str, dict]) -> dict[str, dict]:
    courses, missing = fetch_courses(session)
    fresh = {c["jxb_id"]: c for c in courses}
    log.info("本轮拉取 %d 个教学班", len(fresh))
    current = _carry_over_missing(state, fresh, missing)
    choosed, choosed_notes = resolve_choosed(session)
    sw_state = _load_swap_state()
    held = _held_from_choosed(set(choosed)) if choosed is not None else None
    watched = _watched_ids(sw_state, held)
    log.info("当前监控 %d 个更高优先级教学班", len(watched))
    if choosed is not None:
        _log_conflict_marks(conflict_marks(current, watched, choosed), current, choosed)
    if not state:
        log.info("首轮:保存初始快照,不发普通变更通知")
        changes = []
    else:
        changes = diff(state, current, watched)
    if changes:
        log.info("检测到 %d 条变更", len(changes))
    swap_results = []
    if config.AUTO_SWAP:
        before = dict(choosed) if choosed is not None else None
        try:
            # 目标只从本轮真实抓到的数据里选:沿用上一轮的行可能已经过期,
            # 拿它去退课再选课有换不回来的风险。
            swap_results = maybe_auto_swap(
                session, _open_targets(fresh, watched), current, choosed
            )
        except Exception as e:
            log.exception("auto swap 异常: %s", e)
        if choosed is not None and choosed != before:
            # 换课改变了已选:立即改写记录,下一轮抓取失败时沿用的是换课后的状态。
            save_choosed(choosed)
    all_changes = choosed_notes + list(changes) + swap_results
    if all_changes:
        # 变更和自动换班结果统一通知。
        try:
            notifier.send(all_changes)
        except Exception as e:
            log.warning("通知发送异常: %s", e)
        append_log(all_changes)
    save_state(current)
    return current


def main_loop() -> None:
    session = requests.Session()
    # 与全量抓取/换课共用同一次登录:各自 login 会互相把对方的会话顶掉(见 session_store)。
    ensure_session(session)
    state = load_state()
    backoff = 0
    while True:
        try:
            state = run_once(session, state)
            backoff = 0
        except SessionExpired as e:
            log.info("session 失效,取共享会话/重新登录: %s", e)
            try:
                ensure_session(session, force=True)
            except LoginError as le:
                log.error("重新登录失败,5 分钟后重试: %s", le)
                time.sleep(300)
            continue
        except requests.RequestException as e:
            backoff = min(backoff * 2 + 30, 600)
            log.warning("网络异常,%d 秒后重试: %s", backoff, e)
            time.sleep(backoff)
            continue
        except Exception as e:
            log.exception("未预期错误,30 秒后重试: %s", e)
            time.sleep(30)
            continue
        sleep_s = random.uniform(config.POLL_MIN, config.POLL_MAX)
        log.info("休眠 %.1f 秒", sleep_s)
        time.sleep(sleep_s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="只跑一轮")
    ap.add_argument("--debug", action="store_true", help="DEBUG 日志")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    def _bye(signum, frame):
        log.info("收到信号 %s,退出", signum)
        sys.exit(0)

    signal.signal(signal.SIGINT, _bye)
    signal.signal(signal.SIGTERM, _bye)

    if args.once:
        s = requests.Session()
        ensure_session(s)
        state = load_state()
        run_once(s, state)
    else:
        main_loop()


if __name__ == "__main__":
    main()
