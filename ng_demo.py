"""ng 演示模式的离线示例数据。

面向应用商店审核与非交大用户:无需 JAccount、无需校园网即可体验全部界面。
数据形状与 gui_backend.build_snapshot 一致;演示模式下一切联网与写盘操作都被
ng_service 拒绝,这里的方案编辑只保存在内存里。
"""
from __future__ import annotations

import copy
from typing import Any

import ng_logic

GENERATED_AT = "2026-09-01T09:30:00"
TERM_LABEL = "2026-2027 第1学期（秋）"


def _rating(status: str, score=None, count=None, teacher=None, message=None) -> dict[str, Any]:
    return {
        "status": status, "score": score, "count": count, "teacher": teacher,
        "semester": "2025-2026-1" if status == "rated" else None,
        "updated_at": "2026-08-30T20:00:00" if status != "unknown" else None,
        "message": message,
    }


def _rating_text(rating: dict[str, Any]) -> str:
    if rating["status"] == "rated":
        return f"{rating['score']:.1f} / {rating['count']}评"
    return {"empty": "暂无评价", "not_found": "未收录", "teacher_unrated": "本班老师无评价"}.get(rating["status"], "-")


def _course(jxb_id, title, class_no, teacher, sksj, location, kch, category, selected, capacity,
            rating, group=None, chosen=False) -> dict[str, Any]:
    class_name = f"(2026-2027-1)-{kch}-{class_no}"
    open_ = selected < capacity
    schedule = [sksj]
    return {
        "jxb_id": jxb_id,
        "title": title,
        "class_name": class_name,
        "summary": f"{teacher} / {sksj} / {location} / {kch}",
        "detail": f"课程: {title}\n教学班: {class_name}\n教师: {teacher}\n时间: {sksj}\n地点: {location}",
        "teachers": teacher,
        "schedule": schedule,
        "locations": [location],
        "search_text": f"{title} {kch} {jxb_id} {class_name} {teacher} {sksj} {location} {category}".casefold(),
        "seat_text": f"{selected} / {capacity}",
        "availability": "open" if open_ else "full",
        "availability_text": "有空位" if open_ else "已满",
        "group": group,
        "chosen": chosen,
        "category": category,
        "rating": rating,
        "rating_text": _rating_text(rating),
        "kch": kch,
        "sksj": sksj,
    }


def _courses() -> list[dict[str, Any]]:
    return [
        _course("DEMO-EN-01", "学术英语写作", "01", "李明", "星期一第3-4节{1-16周}", "东上院301", "ENGL1201",
                "公共选修", 60, 60, _rating("rated", 4.6, 128, "李明"), group="英语拓展"),
        _course("DEMO-EN-02", "学术英语写作", "02", "王芳", "星期三第3-4节{1-16周}", "东上院302", "ENGL1201",
                "公共选修", 48, 60, _rating("rated", 4.2, 86, "王芳"), group="英语拓展", chosen=True),
        _course("DEMO-EN-03", "学术英语口语", "01", "周洁", "星期二第3-4节{1-16周}", "东上院105", "ENGL1202",
                "公共选修", 31, 40, _rating("rated", 4.7, 42, "周洁")),
        _course("DEMO-CS-01", "数据结构", "03", "张伟", "星期二第1-2节{1-16周}", "电信群楼3-200", "CS0501",
                "主修", 112, 150, _rating("rated", 4.8, 210, "张伟")),
        _course("DEMO-CS-02", "数据结构", "05", "刘洋", "星期三第3-4节{1-16周}", "电信群楼3-406", "CS0501",
                "主修", 150, 150, _rating("teacher_unrated", 4.5, 210,
                                          message="选课社区收录了这门课，但没有 刘洋 的评价（分数为课程平均）")),
        _course("DEMO-CS-03", "计算机系统基础", "01", "吴刚", "星期四第1-2节{1-16周}", "电信群楼3-100", "CS2301",
                "主修", 88, 120, _rating("rated", 3.9, 64, "吴刚")),
        _course("DEMO-PH-01", "大学物理（II）", "01", "陈静", "星期四第5-6节{1-16周}", "东中院1-105", "PHY1202",
                "主修", 90, 90, _rating("empty", None, 0), chosen=True),
        _course("DEMO-MA-01", "概率统计", "02", "黄磊", "星期五第1-2节{1-16周}", "东下院201", "MATH1207",
                "主修", 70, 80, _rating("rated", 4.1, 97, "黄磊")),
        _course("DEMO-AR-01", "中国古典园林艺术", "01", "何雨", "星期二第11-12节{1-16周}", "陈瑞球楼101", "ART1105",
                "交叉课程", 52, 60, _rating("rated", 4.9, 305, "何雨")),
        _course("DEMO-AR-02", "电影与现代社会", "01", "郑欣", "星期一第11-13节{1-11周}", "陈瑞球楼207", "ART1203",
                "交叉课程", 120, 120, _rating("rated", 4.4, 77, "郑欣")),
        _course("DEMO-PE-01", "篮球", "01", "赵强", "星期五第7-8节{1-16周}", "体育馆篮球场", "PE0301",
                "体育", 28, 40, _rating("not_found", message="选课社区暂无该课程记录"), group="体育项目"),
        _course("DEMO-PE-02", "羽毛球", "02", "孙丽", "星期三第7-8节{1-16周}", "体育馆羽毛球馆", "PE0307",
                "体育", 36, 36, _rating("rated", 4.4, 54, "孙丽"), group="体育项目"),
        _course("DEMO-PE-03", "游泳", "01", "钱涛", "星期三第3-4节{1-16周}", "游泳馆", "PE0311",
                "体育", 20, 30, _rating("rated", 4.3, 33, "钱涛")),
    ]


INITIAL_GROUPS = {
    "英语拓展": {"is_pe": False, "priority": ["DEMO-EN-01", "DEMO-EN-02"]},
    "体育项目": {"is_pe": True, "priority": ["DEMO-PE-01", "DEMO-PE-03", "DEMO-PE-02"]},
}

_DEMO_LOG = [
    "2026-09-01T08:00:02 INFO [monitor] 监控启动：2 个方案 / 5 个教学班",
    '2026-09-01T08:00:05 {"kind": "choosed_fetch_recovered", "count": 2}',
    '2026-09-01T08:31:40 {"kind": "changes", "kcmc": "学术英语写作", "jxbmc": "(2026-2027-1)-ENGL1201-02", "changes": {"jxbxzrs": [49, 48]}}',
    '2026-09-01T08:47:12 {"kind": "spot_open", "kcmc": "篮球", "jxbmc": "(2026-2027-1)-PE0301-01", "msg": "有空位! 28/40"}',
    '2026-09-01T08:47:13 {"kind": "conflict_skipped", "kcmc": "游泳", "jxbmc": "(2026-2027-1)-PE0311-01", "conflict_group": "英语拓展", "detail": "周三 第3节 (第1周)"}',
    '2026-09-01T09:15:00 {"kind": "swap_result", "ok": true, "dry_run": true, "kcmc": "篮球", "jxbmc": "(2026-2027-1)-PE0301-01"}',
    "2026-09-01T09:20:44 WARNING [zzxk] JxbWithKch 响应较慢，已重试一次",
]


class DemoState:
    """演示会话:方案可以在内存里编辑,但不会保存。"""

    def __init__(self) -> None:
        self.courses = _courses()
        self.groups = copy.deepcopy(INITIAL_GROUPS)

    @property
    def courses_by_id(self) -> dict[str, dict[str, Any]]:
        return {row["jxb_id"]: row for row in self.courses}

    @property
    def choosed(self) -> list[dict[str, Any]]:
        return [
            {"jxb_id": row["jxb_id"], "title": row["title"], "class_name": row["class_name"],
             "sksj": row["sksj"], "group": row["group"]}
            for row in self.courses if row["chosen"]
        ]

    def label_for(self, jxb_id: str | None) -> str:
        row = self.courses_by_id.get(jxb_id or "")
        return f"{row['title']} - {row['class_name']}" if row else "-"

    def snapshot(self) -> dict[str, Any]:
        by_id = self.courses_by_id
        chosen_ids = {row["jxb_id"] for row in self.choosed}
        courses = []
        for row in self.courses:
            owner = next((name for name, g in self.groups.items() if row["jxb_id"] in g["priority"]), None)
            courses.append({**row, "group": owner})
        groups = []
        watched_total = 0
        for name, group in self.groups.items():
            priority = list(group["priority"])
            held = next((jxb_id for jxb_id in priority if jxb_id in chosen_ids), None)
            watched = priority[: priority.index(held)] if held else priority
            watched_total += len(watched)
            marks = ng_logic.group_conflict_marks(priority, by_id, self.choosed)
            groups.append({
                "name": name,
                "is_pe": group["is_pe"],
                "priority": priority,
                "held": held,
                "held_label": self.label_for(held),
                "watched_count": len(watched),
                "fatal": False,
                "members": [],
                "conflicts": marks,
                "conflict_count": len(marks),
            })
        state_rows = [
            {
                "jxb_id": row["jxb_id"],
                "watched": any(row["jxb_id"] in g["priority"] and row["jxb_id"] not in chosen_ids for g in self.groups.values()),
                "group": row["group"],
                "title": row["title"],
                "summary": row["summary"],
                "seat_text": row["seat_text"],
                "open": row["availability"] == "open",
            }
            for row in courses if row["group"]
        ]
        return {
            "generated_at": GENERATED_AT,
            "metrics": {
                "queries": len({by_id[i]["kch"] for g in self.groups.values() for i in g["priority"] if i in by_id}),
                "groups": len(self.groups),
                "snapshot": len(state_rows),
                "watched": watched_total,
                "open_courses": sum(row["availability"] == "open" for row in courses),
                "interval": "60-120s",
                "auto_swap": "dry_run",
            },
            "settings": {
                "jaccount_user": "demo", "jaccount_pass": "", "course_plus_password": "",
                "has_jaccount_pass": True, "has_course_plus_password": False,
                "poll_min": 60, "poll_max": 120, "email_enabled": False,
                "smtp_host": "mail.sjtu.edu.cn", "smtp_port": 465, "smtp_user": "", "smtp_pass": "",
                "has_smtp_pass": True, "smtp_pass_fallback": True, "secret_backend": "演示模式（不写入）",
                "mail_from": "", "mail_to": "",
            },
            "onboarding": {"completed": True, "has_account": True, "catalog_ready": True},
            "user": {
                "name": "示例同学", "student_id": "526000000000", "class_name": "示例班级",
                "major": "计算机科学与技术", "term": TERM_LABEL, "catalog_fetched_at": GENERATED_AT,
            },
            "terms": [{
                "key": "2026-3", "xkxnm": "2026", "xkxqm": "3", "label": TERM_LABEL, "active": True,
                "group_count": len(self.groups), "catalog_fetched_at": GENERATED_AT, "is_site_term": True,
            }],
            "active_term": "2026-3",
            "site_term": {
                "key": "2026-3", "label": TERM_LABEL, "zzxk_open": True, "tjxkbkk_open": True,
                "detected_at": GENERATED_AT, "matches_active": True,
            },
            "groups": groups,
            "courses": courses,
            "choosed": self.choosed,
            "choosed_at": "2026-09-01T09:15:00",
            "state_rows": state_rows,
            "swap_state": {"completed": ["DEMO-EN-02"], "fatal": [], "fatal_groups": []},
            "swap_history": [
                {"timestamp": "2026-09-01T09:15:00", "dry_run": True, "group": "体育项目", "target": "DEMO-PE-01",
                 "drop": None, "ok": True, "status": "DRY_RUN", "kcmc": "篮球"},
                {"timestamp": "2026-08-30T21:02:11", "dry_run": False, "group": "英语拓展", "target": "DEMO-EN-02",
                 "drop": "DEMO-EN-03", "ok": True, "status": "ok", "kcmc": "学术英语写作"},
            ],
            "categories": sorted({row["category"] for row in courses}),
            "running": [],
            "release_mode": False,
        }

    def log_entries(self) -> list[dict[str, str]]:
        return [ng_logic.parse_log_line("changes", line) for line in _DEMO_LOG]
