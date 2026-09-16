"""course.sjtu.plus(选课社区)登录 + 按课程编号查评分。

与 jaccount 完全无关联的独立站点账号体系(邮箱+密码),抓包(2026-07-08 HAR)验证:
  - 未登录访问任何 /api/ 接口一律 401。
  - 登录流程: GET /api/auth/csrf 拿 x-csrf-token 响应头,
    POST /api/auth/login 带该 token 提交 {email, password}。
  - 登录后是标准会话态,requests.Session 自动接管 cookie,无需手工解析。
  - 评分内嵌在 /api/course/{id} 里: rating.{count, avg, score, distribution}。
  - 列表项也直接带 rating,不必再逐个查详情。

评分是**按老师**分开的(2026-09-16 实测): 同一课程代码下每位老师一条记录,
CS0501 有 28 条、MARX1205 有 116 条。所以:
  - 必须翻页取全 —— 只取第一页(旧实现 page_size=20)大概率根本没取到本班老师;
  - 列表默认按评分从高到低,匹配不上就取第一条 = 拿了"分最高的那位老师"冒充,
    表现就是"课程对、老师不对"(用户实测反馈的问题);
  - main_teacher.code 就是教务的**教师工号**(如 10498 郭晓莉),与教务 jsxx 里的
    "10498/郭晓莉/副研究员" 完全对得上 —— 按工号匹配比姓名可靠(可避免重名)。

对外主要接口:
  login(session)                              → 登录,幂等
  search_course_by_code(session, code)        → 按课程代码精确匹配的全部候选(自动翻页)
  fetch_course_ratings(session, code)         → 按老师聚合的评分表(工号/姓名双索引)
  get_course_detail(session, course_id)       → 单课详情(含 rating)
  get_rating_by_code(session, code, teacher)  → 便捷入口,返回精简评分字典
"""
from __future__ import annotations

import logging
import sys

import requests

import config

log = logging.getLogger(__name__)

BASE = "https://course.sjtu.plus/api"
CSRF_URL = f"{BASE}/auth/csrf"
LOGIN_URL = f"{BASE}/auth/login"
API_KEY_PROBE_URL = f"{BASE}/api-key/"
COURSE_LIST_URL = f"{BASE}/course/"
COURSE_DETAIL_URL = f"{BASE}/course/{{id}}"


class LoginError(RuntimeError):
    pass


def _resolve_email() -> str:
    """course.sjtu.plus 邮箱: 优先用 .env 里显式配置的 COURSE_PLUS_EMAIL(手工覆盖用);

    否则回退为 jaccount 用户名同前缀的 @sjtu.edu.cn 邮箱 —— 该站账号邮箱与
    jaccount 用户名相同前缀这件事已由用户实测确认,GUI 因此不再单独收用户名。
    """
    if config.COURSE_PLUS_EMAIL:
        return config.COURSE_PLUS_EMAIL
    if config.JACCOUNT_USER:
        return f"{config.JACCOUNT_USER}@sjtu.edu.cn"
    return ""


def _is_logged_in(session: requests.Session) -> bool:
    try:
        r = session.get(
            API_KEY_PROBE_URL,
            headers={"User-Agent": config.USER_AGENT},
            timeout=10,
        )
        return r.status_code == 200
    except requests.RequestException:
        return False


def login(session: requests.Session) -> None:
    email = _resolve_email()
    if not email or not config.COURSE_PLUS_PASSWORD:
        raise LoginError(
            "course.sjtu.plus 邮箱/密码未配置: 需要 JACCOUNT_USER(或 COURSE_PLUS_EMAIL) "
            "+ COURSE_PLUS_PASSWORD"
        )

    session.headers.setdefault("User-Agent", config.USER_AGENT)

    if _is_logged_in(session):
        log.info("session 仍有效,跳过登录")
        return

    csrf_resp = session.get(CSRF_URL, timeout=10)
    token = csrf_resp.headers.get("x-csrf-token")
    if not token:
        raise LoginError(f"未拿到 csrf token(HTTP {csrf_resp.status_code})")

    login_resp = session.post(
        LOGIN_URL,
        json={"email": email, "password": config.COURSE_PLUS_PASSWORD},
        headers={"x-csrf-token": token},
        timeout=10,
    )
    if login_resp.status_code != 200:
        raise LoginError(
            f"登录失败: HTTP {login_resp.status_code} {login_resp.text[:200]!r}"
        )

    if not _is_logged_in(session):
        raise LoginError("登录请求返回 200 但会话探针仍未通过,请检查响应体")

    log.info("course.sjtu.plus 登录成功")


def search_course_by_code(
    session: requests.Session, code: str, *,
    page_size: int = 100, max_pages: int = 5,
) -> list[dict]:
    """按课程代码取回**全部**精确匹配的候选(q 是模糊搜索,要自己过滤 code)。

    一位老师一条记录,热门通识课能有一百多条,必须翻页;只取一页会漏掉本班老师,
    进而退化成"拿别人的评分冒充"。
    """
    items: list[dict] = []
    seen: set[int] = set()
    for page in range(1, max_pages + 1):
        r = session.get(
            COURSE_LIST_URL,
            params={"q": code, "page": page, "page_size": page_size},
            timeout=15,
        )
        r.raise_for_status()
        payload = r.json()
        rows = payload.get("items") or []
        for item in rows:
            if item.get("code") == code and item.get("id") not in seen:
                seen.add(item.get("id"))
                items.append(item)
        total = payload.get("total")
        if len(rows) < page_size or (isinstance(total, int) and page * page_size >= total):
            break
    return items


def _entry(item: dict) -> dict:
    teacher = item.get("main_teacher") or {}
    return {
        "course_id": item.get("id"),
        "name": item.get("name"),
        "teacher": teacher.get("name"),
        "teacher_id": str(teacher.get("code") or "") or None,  # = 教务的教师工号
        "semester": item.get("last_semester"),
        "rating": item.get("rating"),
    }


def _entry_rank(entry: dict) -> tuple:
    """同一位老师有多条(不同学期)时选哪条:学期新的优先,其次评价数多的。"""
    rating = entry.get("rating") or {}
    return (str(entry.get("semester") or ""), rating.get("count") or 0)


def fetch_course_ratings(session: requests.Session, code: str, **search_kwargs) -> dict | None:
    """把某课程代码下所有老师的评分整理成可按老师精确取用的结构。

    返回 {code, name, teachers: {工号: entry}, by_name: {姓名: 工号或姓名},
          entries: [...]};站上没有这门课时返回 None。
    """
    candidates = search_course_by_code(session, code, **search_kwargs)
    if not candidates:
        return None
    entries = [_entry(item) for item in candidates]
    teachers: dict[str, dict] = {}
    by_name: dict[str, str] = {}
    for entry in entries:
        key = entry["teacher_id"] or entry["teacher"]
        if not key:
            continue
        if key not in teachers or _entry_rank(entry) > _entry_rank(teachers[key]):
            teachers[key] = entry
        if entry["teacher"]:
            by_name.setdefault(entry["teacher"], key)
    return {
        "code": code,
        "name": next((e["name"] for e in entries if e.get("name")), None),
        "teachers": teachers,
        "by_name": by_name,
        "entries": entries,
    }


def get_course_detail(session: requests.Session, course_id: int) -> dict:
    r = session.get(COURSE_DETAIL_URL.format(id=course_id), timeout=10)
    r.raise_for_status()
    return r.json()


def get_rating_by_code(
    session: requests.Session, code: str, teacher_name: str | None = None,
    teacher_id: str | None = None,
) -> dict | None:
    """按课程代码查评分;给了老师(工号优先、姓名次之)就只返回该老师的那条。

    找不到该老师时返回 None —— 宁可"没有",也不要把别的老师的评分安到这门班上。
    """
    table = fetch_course_ratings(session, code)
    if not table:
        return None
    entry = lookup_teacher(table, teacher_id=teacher_id, teacher_name=teacher_name)
    if entry:
        return {"code": code, **{k: entry[k] for k in
                                 ("teacher", "teacher_id", "semester", "rating")}}
    if teacher_id or teacher_name:
        return None
    best = max(table["entries"], key=_entry_rank, default=None)
    return None if best is None else {
        "code": code, **{k: best[k] for k in
                         ("teacher", "teacher_id", "semester", "rating")}
    }


def lookup_teacher(table: dict, *, teacher_id: str | None = None,
                   teacher_name: str | None = None) -> dict | None:
    """在评分表里按工号(优先)或姓名找一位老师;都没命中返回 None。"""
    teachers = table.get("teachers") or {}
    if teacher_id and teacher_id in teachers:
        return teachers[teacher_id]
    if teacher_name:
        key = (table.get("by_name") or {}).get(teacher_name)
        if key and key in teachers:
            return teachers[key]
    return None


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    if len(sys.argv) < 2:
        print(f"用法: python {sys.argv[0]} <课程代码> [老师姓名]")
        sys.exit(1)

    kch = sys.argv[1]
    teacher = sys.argv[2] if len(sys.argv) > 2 else None

    s = requests.Session()
    login(s)
    result = get_rating_by_code(s, kch, teacher)
    print(result if result is not None else f"未找到课程代码 {kch} 的评分数据")
