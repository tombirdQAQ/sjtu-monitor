"""初始化向导:自动抓取选课所需的用户信息、课程目录和已选课程。

用法:
  python bootstrap.py                 # 全流程:用户信息 + 全量课程目录 + 已选课程
  python bootstrap.py --debug
  python bootstrap.py --skip-catalog  # 只抓用户信息和已选,不抓课程目录
  python bootstrap.py --with-capacity # 目录附带容量/教师/时间(逐课多查一次,慢)
  python bootstrap.py --detect-term   # 只读取教务网站当前选课学期与模块开放状态
  python bootstrap.py --adopt-site-term # 学期与教务网站不一致时切换到网站学期(首次引导用)

抓取前先读取教务网站当前选课学期:没有开放的选课模块(非选课期间)或与当前学期不一致时
不抓取、不写盘,以非 0 退出码结束,并输出一行 RESULT_PREFIX + JSON 供 GUI 提示原因。

产出:
  1. user_settings.json 的 query_overrides / site_term 分区 —— 个人查询参数自动填充,
     新用户无需再从 HAR 手工提取 zyh_id / njdm_id 等字段;
  2. 当前学期目录下的 catalog.json —— 全量课程目录(课程 + 教学班)及当前已选课程,
     供 GUI"课程方案"页选择监控目标、排优先级。

数据来源(2026-07-06 联网实测):
  - 选课首页 PAGE_URL 的 hidden input   → 个人查询参数、选课学年学期
  - kbcx/xskbcx_cxXsgrkb (个人课表)     → zyh_id / njdm_id / 姓名学号
  - zzxkyzb 自主选课模块 (zzxk.py)      → 全部非体育课程目录(主修/通识/公选/任选/交叉)
    ⚠ tjxkbkk display 空 kch_id 查询实测不返回数据,已弃用该目录来源
  - xsxk/..._cxJxbTjxkBkk 空 kch_id     → 体育课目录(tjxkbkk,保留原接口)
  - tjxkbkk ChoosedCourse + zzxkyzb ChoosedDisplay → 两个轮次的当前已选
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime

import requests

import config
import course_plus
import zzxk
from login import LoginError, ensure_session, is_logged_in

log = logging.getLogger("bootstrap")

_HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": config.REFERER,
    "Origin": "https://i.sjtu.edu.cn",
    "User-Agent": config.USER_AGENT,
}
_PAGE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "User-Agent": config.USER_AGENT,
}

# hidden input 里这些 key 属于"每次查询单独给"的参数,不写进个人覆盖
_NON_PERSONAL_KEYS = {"kch_id", "jxb_id", "kklxdm", "bklx_id", "xkxnm", "xkxqm"}

# catalog.json 里每个教学班保留的字段(全量字段太大,只留展示和监控要用的)
_CLASS_FIELDS = (
    "jxb_id", "jxbmc", "kch", "kcmc",
    "jsxx", "sksj", "jxdd", "xf", "jxbxf", "kcxzmc", "kklxdm", "kzmc",
    "cxbj", "fxbj", "xxkbj",
)


def _parse_hidden_inputs(html: str) -> dict[str, str]:
    """提取页面中全部 <input type="hidden"> 的 id/name → value。"""
    found: dict[str, str] = {}
    for tag in re.findall(r"<input\b[^>]*>", html, re.I):
        if not re.search(r"type\s*=\s*[\"']hidden[\"']", tag, re.I):
            continue
        m_key = re.search(r"(?:id|name)\s*=\s*[\"']([^\"']+)[\"']", tag, re.I)
        m_val = re.search(r"value\s*=\s*[\"']([^\"']*)[\"']", tag, re.I)
        if m_key and m_val:
            found.setdefault(m_key.group(1), m_val.group(1))
    return found


def _page_params_from_hidden(hidden: dict[str, str]) -> dict[str, str]:
    known = set(config.query_common("display")) | set(config.query_common("pe"))
    params = {k: v for k, v in hidden.items() if k in known}
    log.info("[首页] 共 %d 个 hidden input,命中查询参数 %d 个: %s",
             len(hidden), len(params), sorted(params))
    return params


def fetch_page_params(session: requests.Session) -> dict[str, str]:
    """GET 选课首页,收集 hidden input 里的查询参数(个人字段 + 学期)。"""
    r = session.get(
        config.PAGE_URL, headers=_PAGE_HEADERS, timeout=15, allow_redirects=False
    )
    if r.status_code != 200:
        raise RuntimeError(f"选课首页返回 status={r.status_code},session 可能失效")
    return _page_params_from_hidden(_parse_hidden_inputs(r.text))


# GUI 从进程输出里识别这一行,解析失败原因并弹窗提示。
RESULT_PREFIX = "[bootstrap-result] "


class BootstrapFailure(RuntimeError):
    """需要提示用户的失败:非选课期间/学期不一致/没有抓到任何数据。"""

    EXIT_CODES = {"error": 1, "term_mismatch": 2, "closed": 3, "empty": 4,
                  "session": 5}

    def __init__(self, reason: str, message: str, **extra) -> None:
        super().__init__(message)
        self.reason = reason
        self.extra = extra

    @property
    def exit_code(self) -> int:
        return self.EXIT_CODES.get(self.reason, 1)


def emit_result(result: dict) -> None:
    print(RESULT_PREFIX + json.dumps(result, ensure_ascii=False), flush=True)


def detect_site_term(session: requests.Session) -> tuple[dict, dict[str, str], dict[str, str]]:
    """读取教务网站当前选课学期,返回 (site_term, zzxk 首页 hidden, 补退选首页 hidden)。

    2026-09 联网实测:两个模块首页 hidden 均含 xkxnm/xkxqm(2026/3),zzxk 首页另有
    xkxnmc(2026-2027)/xkxqmc(1);个人课表页默认学期一致。
    开放判定:zzxk 首页含分类页签(queryCourse);补退选首页 200 且带 xkxnm 与 xkkz_id。
    非选课期间的页面形态尚未实测,两个模块都判定未开放即视为不可抓取。
    """
    site: dict = {"zzxk_open": False, "tjxkbkk_open": False}
    zzxk_hidden: dict[str, str] = {}
    page_hidden: dict[str, str] = {}
    try:
        zzxk_hidden, tabs = zzxk.fetch_index(session)
        site["zzxk_open"] = bool(tabs)
    except Exception as e:
        site["zzxk_error"] = str(e)[:200]
        log.info("[学期] 自主选课模块不可用: %s", e)
    try:
        r = session.get(config.PAGE_URL, headers=_PAGE_HEADERS, timeout=15,
                        allow_redirects=False)
        if r.status_code == 200:
            page_hidden = _parse_hidden_inputs(r.text)
        site["tjxkbkk_open"] = bool(
            r.status_code == 200 and page_hidden.get("xkxnm") and page_hidden.get("xkkz_id")
        )
        if not site["tjxkbkk_open"]:
            site["tjxkbkk_error"] = f"status={r.status_code}"
    except Exception as e:
        site["tjxkbkk_error"] = str(e)[:200]
        log.info("[学期] 补退选模块不可用: %s", e)
    for hidden, is_open in ((zzxk_hidden, site["zzxk_open"]), (page_hidden, site["tjxkbkk_open"])):
        if is_open and hidden.get("xkxnm") and hidden.get("xkxqm"):
            site["xkxnm"], site["xkxqm"] = hidden["xkxnm"], hidden["xkxqm"]
            break
    for key in ("xkxnmc", "xkxqmc"):
        if zzxk_hidden.get(key):
            site[key] = zzxk_hidden[key]
    if site.get("xkxnm"):
        site["label"] = config.term_label(site["xkxnm"], site["xkxqm"], site)
        log.info("[学期] 教务网站当前选课学期: %s (xkxnm=%s xkxqm=%s) 自主选课=%s 补退选=%s",
                 site["label"], site["xkxnm"], site["xkxqm"],
                 "开放" if site["zzxk_open"] else "未开放",
                 "开放" if site["tjxkbkk_open"] else "未开放")
    elif not is_logged_in(session):
        # 掉登录时两个模块的首页都会被重定向,读不到 hidden —— 形态和"非选课期间"
        # 一模一样。这里显式探一次,免得把掉线报成"不在选课学期"(实测踩过)。
        site["session_error"] = True
        log.warning("[学期] 两个选课模块都读不到,且当前会话已失效:是掉登录,不是非选课期间")
    else:
        log.warning("[学期] 未读取到开放的选课模块,可能非选课期间")
    return site, zzxk_hidden, page_hidden


def check_site_term(site: dict, adopt_site_term: bool = False) -> None:
    """网站学期与当前学期一致才允许抓取;adopt_site_term 时直接切换到网站学期。"""
    active_label = config.term_label(config.XKXNM, config.XKXQM, site)
    if not site.get("xkxnm") and site.get("session_error"):
        raise BootstrapFailure(
            "session",
            f"登录会话已失效，读不到「{active_label}」的选课页面。教务网站同一账号同时"
            "只允许一个登录会话，被别处登录顶掉时就会这样。请重试一次；若反复出现，"
            "检查是否还有旧版本的监控进程在单独登录。",
            term=active_label,
        )
    if not site.get("xkxnm"):
        raise BootstrapFailure(
            "closed",
            f"教务网站当前没有开放的选课模块，可能不在选课期间，无法获取「{active_label}」的全量课程。"
            "请在选课开放后重试。",
            term=active_label,
        )
    site_key = config.term_key(site["xkxnm"], site["xkxqm"])
    if site_key == config.ACTIVE_TERM:
        return
    if adopt_site_term:
        config.set_active_term(site["xkxnm"], site["xkxqm"])
        log.info("[学期] 已切换到教务网站当前学期 %s", site.get("label"))
        return
    raise BootstrapFailure(
        "term_mismatch",
        f"教务网站当前选课学期为「{site.get('label')}」，与方案所选学期「{active_label}」不一致，"
        "教务网站无法返回所选学期的课程。请在课程方案页切换到该学期后再获取，或等所选学期开放选课。",
        term=active_label,
        site_term=site.get("label"),
        site_key=site_key,
    )


def xsxx_query_variants(term: tuple[str, str] | None = None) -> list[dict]:
    variants: list[dict] = [{"xnm": "", "xqm": "", "kzlx": "ck"}]
    candidates = []
    if term and term[0]:
        candidates.append((term[0], term[1] or ""))
    candidates.append((config.XKXNM, config.XKXQM))
    seen = {("", "")}
    for xnm, xqm in candidates:
        key = (str(xnm or ""), str(xqm or ""))
        if not key[0] or key in seen:
            continue
        seen.add(key)
        variants.append({"xnm": key[0], "xqm": key[1], "kzlx": "ck"})
    return variants


def fetch_xsxx(
    session: requests.Session, term: tuple[str, str] | None = None
) -> dict:
    """个人课表接口的 xsxx 块:ZYH_ID/NJDM_ID/XM/XH/BJMC/ZYMC。

    实测(2026-07):空学年学期服务端返回 null,须带当前学期重试;
    学期提示 term=(xnm, xqm) 可取自 zzxk 首页 hidden 的 xkxnm/xkxqm。
    """
    for data in xsxx_query_variants(term):
        r = session.post(
            config.XSGRKB_URL, data=data,
            headers=_HEADERS, timeout=15, allow_redirects=False,
        )
        if "application/json" not in r.headers.get("content-type", ""):
            raise RuntimeError(f"cxXsgrkb 非 JSON 响应: status={r.status_code}")
        payload = r.json()
        xsxx = (payload or {}).get("xsxx") or {}
        if xsxx:
            log.info("[身份] %s (%s) %s %s",
                     xsxx.get("XM"), xsxx.get("XH"),
                     xsxx.get("BJMC"), xsxx.get("ZYMC"))
            return xsxx
        log.debug("cxXsgrkb 参数 %s 返回空,尝试下一组", data)
    return {}


def fetch_choosed(session: requests.Session) -> list[dict]:
    """当前已选课程列表。"""
    common = config.query_common("display")
    data = {
        k: common.get(k, "")
        for k in ("xkxnm", "xkxqm", "xkly", "njdm_id", "zyh_id",
                  "zyfx_id", "bh_id", "xz", "ccdm")
    }
    r = session.post(
        config.CHOOSED_URL, data=data, headers=_HEADERS,
        timeout=15, allow_redirects=False,
    )
    if r.status_code in zzxk.SESSION_STATUSES:
        raise zzxk.SessionExpired(
            f"tjxkbkk 已选 {zzxk.SESSION_HINT}: status={r.status_code}")
    if "application/json" not in r.headers.get("content-type", ""):
        raise RuntimeError(f"choosed 非 JSON 响应: status={r.status_code}")
    result = r.json()
    return result if isinstance(result, list) else []


def _to_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def availability_from_row(row: dict) -> str:
    selected = _to_int(row.get("jxbxzrs", row.get("yxzrs")))
    capacity = _to_int(row.get("jxbrl"))
    if selected is None or capacity is None or capacity <= 0:
        return "unknown"
    return "open" if selected < capacity else "full"


def _slim_class(cls: dict, *, include_availability: bool = True) -> dict:
    out = {k: cls.get(k) for k in _CLASS_FIELDS if cls.get(k) is not None}
    if include_availability:
        out["availability"] = availability_from_row(cls)
    return out


def fetch_zzxk_catalog(
    session: requests.Session, with_capacity: bool = False
) -> list[dict]:
    """经 zzxkyzb 模块抓全量非体育课程目录(联网实测可用)。

    zzxk.fetch_full_catalog 已做 yxzrs→jxbxzrs 归一化;这里再走 _slim_class
    统一裁剪字段,保证 catalog.json 里 pe/zzxk 两来源的教学班结构一致。
    """
    # 目录没有独立空位接口:PartDisplay 给人数,JxbWithKch 给容量。
    # 两者只在内存中比较,原始数字不写 catalog.json。
    courses = zzxk.fetch_full_catalog(session, with_capacity=True)
    for course in courses:
        course["classes"] = [_slim_class(c) for c in course["classes"]]
    return courses


def fetch_pe_catalog(session: requests.Session) -> list[dict]:
    """空 kch_id 查询体育课接口,返回体育课目录(按 kch 分组)。"""
    payload = {**config.query_common("pe"), "kch_id": ""}
    r = session.post(
        config.JXB_LIST_URL, data=payload, headers=_HEADERS,
        timeout=30, allow_redirects=False,
    )
    if "application/json" not in r.headers.get("content-type", ""):
        raise RuntimeError(f"pe 目录查询非 JSON 响应: status={r.status_code}")
    data = r.json()
    class_rows = data if isinstance(data, list) else []
    if not class_rows:
        # 实测(2026-07): 空 kch_id 不返回数据 → 回退为逐课查询已配置的体育课
        # (仍是同一 cxJxbTjxkBkk 接口,保持体育课接口不变)
        log.info("[目录] pe 空查询无数据,回退为逐课查询已配置体育课")
        for kch, q in config.KCH_QUERIES.items():
            if q.get("endpoint") != "pe":
                continue
            qp = config.build_query_payload(kch)
            if qp is None:
                continue
            url, per_payload = qp
            resp = session.post(url, data=per_payload, headers=_HEADERS,
                                timeout=15, allow_redirects=False)
            if "application/json" in resp.headers.get("content-type", ""):
                rows = resp.json()
                if isinstance(rows, list):
                    class_rows += rows
    if not class_rows:
        log.warning("[目录] pe 目录为空(该轮次可能未开放)")
        return []
    by_kch: dict[str, dict] = {}
    for cls in class_rows:
        kch = cls.get("kch")
        if not kch:
            continue
        course = by_kch.setdefault(kch, {
            "kch": kch,
            # 体育课查询直接用课程号做 kch_id (与 KCH_QUERIES 现有约定一致)
            "kch_id": kch,
            "kcmc": cls.get("kcmc"),
            "kklxdm": cls.get("kklxdm") or "06",
            "endpoint": "pe",
            "classes": [],
        })
        course["classes"].append(_slim_class(cls))
    log.info("[目录] pe: %d 门课程 / %d 个教学班", len(by_kch), len(class_rows))
    return list(by_kch.values())


def _load_catalog() -> dict:
    """读上一次写好的 catalog.json;不存在或损坏时返回空 dict。"""
    try:
        data = json.loads(config.CATALOG_FILE.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _course_source(course: dict) -> str:
    """课程属于哪个抓取来源:体育课走 pe 接口,其余走 zzxk 全量目录。"""
    endpoint = course.get("endpoint")
    if endpoint in ("pe", "zzxk"):
        return endpoint
    return "pe" if str(course.get("kklxdm") or "") == "06" else "zzxk"


def _previous_courses(previous: dict, source: str) -> list[dict]:
    """上一次 catalog.json 里属于该来源的课程,用作本轮该来源失败/为空时的兜底。"""
    return [
        course for course in (previous.get("courses") or [])
        if isinstance(course, dict) and _course_source(course) == source
    ]


def _save_catalog(catalog: dict) -> None:
    tmp = config.CATALOG_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), "utf-8")
    config.replace_atomic(tmp, config.CATALOG_FILE)


def apply_user_info(page_params: dict[str, str], xsxx: dict) -> None:
    """把抓到的个人参数写进 user_settings.json 的 query_overrides / term 分区。

    优先级: 选课首页 hidden input > cxXsgrkb(仅补 zyh_id/njdm_id)> 已有配置。
    """
    display_keys = set(config.query_common("display")) - _NON_PERSONAL_KEYS
    pe_keys = set(config.query_common("pe")) - _NON_PERSONAL_KEYS
    display_over = {k: v for k, v in page_params.items() if k in display_keys}
    pe_over = {k: v for k, v in page_params.items() if k in pe_keys}
    if xsxx.get("ZYH_ID"):
        display_over.setdefault("zyh_id", xsxx["ZYH_ID"])
        pe_over.setdefault("zyh_id", xsxx["ZYH_ID"])
    if xsxx.get("NJDM_ID"):
        display_over.setdefault("njdm_id", xsxx["NJDM_ID"])
        pe_over.setdefault("njdm_id", xsxx["NJDM_ID"])

    sections: dict = {}
    old = config.QUERY_OVERRIDES
    sections["query_overrides"] = {
        "display": {**old.get("display", {}), **display_over},
        "pe": {**old.get("pe", {}), **pe_over},
    }
    # 学期由 check_site_term 保证与网站一致,这里不再改写(避免抓取中途切换学期目录)。
    config.update_user_settings(**sections)
    log.info("[设置] 已写入 user_settings.json: display 覆盖 %d 项, pe 覆盖 %d 项",
             len(display_over), len(pe_over))


def run(
    session: requests.Session,
    skip_catalog: bool = False,
    with_capacity: bool = False,
    adopt_site_term: bool = False,
    session_retries: int = 1,
) -> dict:
    """执行初始化流程,返回 catalog dict(同时写盘)。

    先校验教务网站当前学期(失败抛 BootstrapFailure,不写盘);之后每步失败不阻断后续,
    但课程目录与已选全部为空时同样抛 BootstrapFailure。

    单个来源失败或返回空时,沿用上一次 catalog.json 里该来源的数据,绝不用残缺结果
    覆盖已经抓好的目录/已选/用户信息(整轮一无所获才报错退出,由 GUI 弹窗提示)。
    """
    previous = _load_catalog()
    stale: list[str] = []
    session_lost = False
    xsxx: dict = {}
    site, _zzxk_hidden, page_hidden = detect_site_term(session)
    config.record_site_term(site)
    check_site_term(site, adopt_site_term=adopt_site_term)
    term_hint: tuple[str, str] | None = (site["xkxnm"], site["xkxqm"])
    page_params = _page_params_from_hidden(page_hidden) if page_hidden else {}
    try:
        xsxx = fetch_xsxx(session, term=term_hint)
    except Exception as e:
        log.warning("个人课表信息抓取失败(不阻断): %s", e)
    if page_params or xsxx:
        apply_user_info(page_params, xsxx)
    else:
        log.warning("未获取到任何用户信息,user_settings.json 保持不变")

    courses: list[dict] = []
    fresh_courses = 0
    sources = (
        ("zzxk", "zzxk 全量目录",
         lambda s: fetch_zzxk_catalog(s, with_capacity=with_capacity)),
        ("pe", "体育课目录", fetch_pe_catalog),
    )
    for source, label, fetch in sources:
        fetched: list[dict] = []
        if not skip_catalog:
            try:
                fetched = fetch(session)
            except zzxk.SessionExpired as e:
                session_lost = True
                log.warning("%s抓取中断: %s", label, e)
            except Exception as e:
                log.warning("%s抓取失败(不阻断): %s", label, e)
        if fetched:
            courses += fetched
            fresh_courses += len(fetched)
            continue
        # 本轮没拿到 → 保留上一次的结果,不让空结果把已抓好的目录抹掉。
        kept = _previous_courses(previous, source)
        if kept:
            courses += kept
            stale.append(source)
            log.warning("%s本轮无数据,沿用上一次的 %d 门课程(不覆盖)", label, len(kept))

    # 两个轮次的已选课程合并(tjxkbkk 补退选 + zzxkyzb 自主选课),按 jxb_id 去重
    choosed: list[dict] = []
    choosed_ids: set[str] = set()
    choosed_ok = False
    for name, fetch in (("tjxkbkk", fetch_choosed),
                        ("zzxk", lambda s: zzxk.fetch_choosed(s))):
        try:
            batch = fetch(session)
            fresh = [
                _slim_class(c, include_availability=False) for c in batch
                if c.get("jxb_id") and c["jxb_id"] not in choosed_ids
            ]
            choosed_ids.update(c["jxb_id"] for c in fresh)
            choosed += fresh
            choosed_ok = True
            log.info("[已选] %s 轮次: %d 门", name, len(batch))
        except zzxk.SessionExpired as e:
            session_lost = True
            log.warning("%s 已选课程抓取中断: %s", name, e)
        except Exception as e:
            log.warning("%s 已选课程抓取失败(不阻断): %s", name, e)
    fresh_choosed = list(choosed)
    if not choosed_ok:
        # 两个模块都没查成功:空列表和"确实一门没选"无法区分,沿用上一次的记录。
        previous_choosed = previous.get("choosed") or []
        if previous_choosed:
            choosed = previous_choosed
            stale.append("choosed")
            log.warning("已选课程两个接口都失败,沿用上一次的 %d 门(不覆盖)",
                        len(previous_choosed))

    if session_lost and session_retries > 0:
        # 会话在抓取途中被顶掉(用户在网页登录、或别的任务重新登录了)。重新取一次
        # 共享会话后整轮重来,总比把半份目录写进去强。
        log.warning("抓取途中登录会话失效,重新取会话后重试一次")
        ensure_session(session, force=True)
        return run(session, skip_catalog=skip_catalog, with_capacity=with_capacity,
                   adopt_site_term=adopt_site_term,
                   session_retries=session_retries - 1)

    # 个人课表接口失败时 xsxx 为空:逐字段回落到上一次的值,避免把姓名/学号写成 null。
    previous_user = previous.get("user") or {}
    user = {}
    for key, field in (("xm", "XM"), ("xh", "XH"), ("bjmc", "BJMC"),
                       ("zymc", "ZYMC"), ("zyh_id", "ZYH_ID"), ("njdm_id", "NJDM_ID")):
        value = xsxx.get(field)
        if value is None:
            value = previous_user.get(key)
            if value is not None:
                stale.append("user")
        user[key] = value
    catalog = {
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "user": user,
        "courses": courses,
        "choosed": choosed,
    }
    if fresh_courses or fresh_choosed:
        catalog["stale"] = sorted(set(stale))
        _save_catalog(catalog)
        log.info("[目录] 已写入 %s: %d 门课程(本轮新抓 %d), %d 门已选",
                 config.CATALOG_FILE.name, len(courses), fresh_courses, len(choosed))
        if catalog["stale"]:
            log.warning("[目录] 以下部分沿用了上一次的数据: %s",
                        ", ".join(catalog["stale"]))
        if session_lost:
            log.warning("[目录] 抓取途中登录会话被顶掉,结果不完整;"
                        "请停止监控等其他需要登录的任务后重抓一次")
    elif session_lost:
        log.warning("登录会话在抓取途中失效,不写 catalog.json")
        raise BootstrapFailure(
            "session",
            "抓取过程中登录会话被顶掉了（教务网站同一账号同时只允许一个登录会话）。"
            "请先停止监控等其他需要登录的任务，再重新获取全量课程。",
            term=site.get("label"),
        )
    else:
        log.warning("课程目录与已选均为空,不写 catalog.json")
        raise BootstrapFailure(
            "empty",
            f"没有获取到「{site.get('label')}」的任何课程或已选记录，可能该学期选课尚未开放或已结束。"
            "请查看日志页了解具体失败的接口。",
            term=site.get("label"),
        )
    return catalog


def _load_seat_details() -> dict:
    if not config.SEAT_DETAILS_FILE.exists():
        return {"classes": {}, "errors": {}}
    try:
        data = json.loads(config.SEAT_DETAILS_FILE.read_text("utf-8"))
        if isinstance(data, dict):
            data.setdefault("classes", {})
            data.setdefault("errors", {})
            return data
    except Exception:
        pass
    return {"classes": {}, "errors": {}}


def _save_seat_details(details: dict) -> None:
    tmp = config.SEAT_DETAILS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(details, ensure_ascii=False, indent=2), "utf-8")
    config.replace_atomic(tmp, config.SEAT_DETAILS_FILE)


def refresh_seat_details(
    session: requests.Session, jxb_ids: list[str]
) -> dict:
    """Refresh plan-only seat counts without touching monitor state."""
    catalog = json.loads(config.CATALOG_FILE.read_text("utf-8"))
    wanted = set(jxb_ids)
    courses_by_endpoint: dict[str, list[dict]] = {}
    for course in catalog.get("courses", []):
        if any(c.get("jxb_id") in wanted for c in course.get("classes", [])):
            courses_by_endpoint.setdefault(course.get("endpoint", ""), []).append(course)

    fetched: dict[str, dict] = {}
    errors: dict[str, str] = {}
    zzxk_courses = {
        course.get("kch") or course["kch_id"]: {
            "endpoint": "zzxk",
            "kch_id": course["kch_id"],
            "kklxdm": str(course.get("kklxdm") or ""),
        }
        for course in courses_by_endpoint.get("zzxk", [])
    }
    if zzxk_courses:
        try:
            fetched.update(zzxk.fetch_seats(session, zzxk_courses))
        except Exception as exc:
            for course in courses_by_endpoint.get("zzxk", []):
                for cls in course.get("classes", []):
                    if cls.get("jxb_id") in wanted:
                        errors[cls["jxb_id"]] = str(exc)

    for course in courses_by_endpoint.get("pe", []):
        payload = {**config.query_common("pe"), "kch_id": course.get("kch_id", "")}
        try:
            response = session.post(
                config.JXB_LIST_URL,
                data=payload,
                headers=_HEADERS,
                timeout=20,
                allow_redirects=False,
            )
            if "application/json" not in response.headers.get("content-type", ""):
                raise RuntimeError(f"体育课详情非 JSON: status={response.status_code}")
            rows = response.json()
            if isinstance(rows, list):
                fetched.update(
                    {row["jxb_id"]: row for row in rows if row.get("jxb_id")}
                )
        except Exception as exc:
            for cls in course.get("classes", []):
                if cls.get("jxb_id") in wanted:
                    errors[cls["jxb_id"]] = str(exc)

    details = _load_seat_details()
    now = datetime.now().isoformat(timespec="seconds")
    for jxb_id in wanted:
        row = fetched.get(jxb_id)
        if row:
            details["classes"][jxb_id] = {
                "jxbxzrs": row.get("jxbxzrs", row.get("yxzrs")),
                "jxbrl": row.get("jxbrl"),
                # sksj(上课时间) 用于 GUI 跨方案组时间冲突校验;pe 课程原始响应自带,
                # zzxk 课程由 zzxk.fetch_seats 从教学班详情缓存回填。
                "sksj": row.get("sksj"),
                "jxdd": row.get("jxdd"),
                "jsxx": row.get("jsxx"),
                "availability": availability_from_row(row),
                "updated_at": now,
            }
            details["errors"].pop(jxb_id, None)
        else:
            details["errors"][jxb_id] = errors.get(jxb_id, "接口未返回该教学班")
    details["updated_at"] = now
    _save_seat_details(details)
    return details


def _load_ratings() -> dict:
    if not config.RATINGS_FILE.exists():
        return {"courses": {}, "errors": {}}
    try:
        data = json.loads(config.RATINGS_FILE.read_text("utf-8"))
        if isinstance(data, dict):
            data.setdefault("courses", {})
            data.setdefault("errors", {})
            return data
    except Exception:
        pass
    return {"courses": {}, "errors": {}}


def _save_ratings(ratings: dict) -> None:
    tmp = config.RATINGS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(ratings, ensure_ascii=False, indent=2), "utf-8")
    config.replace_atomic(tmp, config.RATINGS_FILE)


def _aggregate_rating(entries: list[dict]) -> dict:
    """课程整体评分 = 各位老师按评价数加权平均,给"本班老师没有评价"时当参考。"""
    total = 0
    weighted = 0.0
    for entry in entries:
        rating = entry.get("rating") or {}
        count = rating.get("count") or 0
        score = rating.get("score")
        if score is None:
            score = rating.get("avg")
        if count and score is not None:
            total += count
            weighted += float(score) * count
    return {"count": total, "score": round(weighted / total, 4) if total else None,
            "teacher_count": len(entries)}


def refresh_ratings(
    courses: list[dict] | None = None, kch_list: list[str] | None = None
) -> dict:
    """按 kch 批量拉 course.sjtu.plus 评分,写入 ratings.json。

    courses=None 时从 catalog.json 读;kch_list=None 时刷新全部,否则只刷新给定课程代码。
    course.sjtu.plus 与 i.sjtu.edu.cn 是完全独立的站点,用自己的 requests.Session 登录,
    不复用 jaccount 的 session。缺凭据/登录失败均只记警告,返回现有缓存,不阻断调用方。
    """
    ratings = _load_ratings()
    if not config.COURSE_PLUS_PASSWORD and not config.COURSE_PLUS_EMAIL:
        log.warning("[评分] COURSE_PLUS_PASSWORD 未配置,跳过评分抓取")
        return ratings

    if courses is None:
        catalog = json.loads(config.CATALOG_FILE.read_text("utf-8"))
        courses = catalog.get("courses", [])
    if kch_list is not None:
        wanted = set(kch_list)
        courses = [c for c in courses if c.get("kch") in wanted]

    cp_session = requests.Session()
    try:
        course_plus.login(cp_session)
    except course_plus.LoginError as exc:
        log.warning("[评分] course.sjtu.plus 登录失败,跳过: %s", exc)
        return ratings

    now = datetime.now().isoformat(timespec="seconds")
    ok = 0
    for course in courses:
        kch = course.get("kch")
        if not kch:
            continue
        try:
            # 整门课所有老师一次取全,按工号/姓名存好,由 GUI 按每个教学班的老师取用。
            table = course_plus.fetch_course_ratings(cp_session, kch)
        except Exception as exc:
            # reason 区分"确实抓取失败,不代表没有评分"(fetch_failed) 与
            # "course.sjtu.plus 没有这门课"(not_found,和"有课但 0 条评价"一样都是
            # 合法的"无评分"状态) —— GUI 靠 reason 展示不同文案,而不是猜错误文本。
            ratings["errors"][kch] = {"reason": "fetch_failed", "message": str(exc)}
            continue
        if table:
            entries = table["entries"]
            ratings["courses"][kch] = {
                "code": kch,
                "name": table.get("name"),
                "teachers": table["teachers"],
                "by_name": table["by_name"],
                # 课程级聚合(旧字段名保持不变,老版本 GUI 也读得懂)
                "rating": _aggregate_rating(entries),
                "teacher": None,
                "semester": max((e.get("semester") or "" for e in entries), default=None),
                "updated_at": now,
            }
            ratings["errors"].pop(kch, None)
            ok += 1
        else:
            ratings["errors"][kch] = {
                "reason": "not_found",
                "message": "course.sjtu.plus 未收录该课程",
            }

    ratings["updated_at"] = now
    _save_ratings(ratings)
    log.info("[评分] 刷新完成: %d 门成功, %d 门失败/未收录", ok, len(ratings["errors"]))
    return ratings


def main():
    ap = argparse.ArgumentParser(description="自动抓取用户信息与课程目录")
    ap.add_argument("--debug", action="store_true", help="DEBUG 日志")
    ap.add_argument("--skip-catalog", action="store_true",
                    help="只抓用户信息和已选,不抓课程目录")
    ap.add_argument("--with-capacity", action="store_true",
                    help="目录附带容量/教师/时间(逐课多查一次 JxbWithKch,慢)")
    ap.add_argument("--seat-details", nargs="+", metavar="JXB_ID",
                    help="仅刷新方案内教学班人数/容量缓存")
    ap.add_argument("--with-ratings", action="store_true",
                    help="抓课程目录时顺带拉取 course.sjtu.plus 评分(逐课查询,较慢)")
    ap.add_argument("--fetch-ratings-all", action="store_true",
                    help="仅刷新 catalog.json 全部课程的 course.sjtu.plus 评分缓存")
    ap.add_argument("--fetch-ratings", nargs="+", metavar="KCH",
                    help="仅刷新指定课程代码的 course.sjtu.plus 评分缓存")
    ap.add_argument("--detect-term", action="store_true",
                    help="只读取教务网站当前选课学期与模块开放状态")
    ap.add_argument("--adopt-site-term", action="store_true",
                    help="学期与教务网站不一致时切换到网站学期后再抓取(首次引导用)")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    if args.fetch_ratings_all or args.fetch_ratings:
        # 评分是 course.sjtu.plus 独立站点,不需要 jaccount session
        result = refresh_ratings(
            kch_list=None if args.fetch_ratings_all else args.fetch_ratings
        )
        print(f"评分刷新: {len(result.get('courses', {}))} 门成功, "
              f"{len(result.get('errors', {}))} 门失败/未收录")
        return

    try:
        _main_with_session(args)
    except BootstrapFailure as exc:
        log.error("%s", exc)
        emit_result({"ok": False, "reason": exc.reason, "message": str(exc), **exc.extra})
        sys.exit(exc.exit_code)
    except LoginError as exc:
        log.error("登录失败: %s", exc)
        emit_result({"ok": False, "reason": "login", "message": f"JAccount 登录失败：{exc}"})
        sys.exit(1)
    except requests.RequestException as exc:
        log.error("网络异常: %s", exc)
        emit_result({"ok": False, "reason": "network",
                     "message": f"无法连接教务网站：{exc}"})
        sys.exit(1)


def _main_with_session(args) -> None:
    session = requests.Session()
    ensure_session(session)
    if args.detect_term:
        site, _, _ = detect_site_term(session)
        config.record_site_term(site)
        emit_result({"ok": True, "action": "detect-term", "site_term": site,
                     "active_term": config.ACTIVE_TERM})
        print(f"教务网站当前选课学期: {site.get('label') or '未开放'}")
        return
    if args.seat_details:
        details = refresh_seat_details(session, args.seat_details)
        failed = [jxb_id for jxb_id in args.seat_details
                  if jxb_id in details.get("errors", {})]
        print(f"详情刷新: {len(args.seat_details) - len(failed)} 成功, {len(failed)} 失败")
        return
    catalog = run(session, skip_catalog=args.skip_catalog,
                  with_capacity=args.with_capacity,
                  adopt_site_term=args.adopt_site_term)
    if args.with_ratings and catalog.get("courses"):
        refresh_ratings(courses=catalog["courses"])

    user = catalog["user"]
    print()
    print(f"用户: {user.get('xm') or '?'} ({user.get('xh') or '?'})  "
          f"{user.get('bjmc') or ''} {user.get('zymc') or ''}")
    print(f"课程目录: {len(catalog['courses'])} 门课程, "
          f"{sum(len(c['classes']) for c in catalog['courses'])} 个教学班")
    print(f"当前已选: {len(catalog['choosed'])} 门")
    print("下一步: 打开 GUI 的\"课程方案\"页挑选监控目标并排优先级。")
    if catalog.get("stale"):
        print(f"注意: {', '.join(catalog['stale'])} 本轮没抓到，已沿用上一次的数据。")
    emit_result({"ok": True, "action": "bootstrap", "term": config.ACTIVE_TERM,
                 "courses": len(catalog["courses"]), "choosed": len(catalog["choosed"]),
                 "stale": catalog.get("stale") or []})


if __name__ == "__main__":
    main()
