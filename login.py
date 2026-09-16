"""jaccount CAS 登录 + ddddocr 验证码识别。

调用 `login(session)` 把 session cookie 装到给定 requests.Session,
失败抛 LoginError。幂等,可在 session 过期后重复调用。

实现要点(2026-06 验证):
- i.sjtu.edu.cn 默认是正方教务的本地登录,要走 /jaccountlogin 才会跳 jaccount。
- jaccount 登录页用 JS 对象 `loginContext = {sid, client, returl, se, v, uuid}`
  存所有参数,不是隐藏 input。
- POST /jaccount/ulogin,字段:sid, client, returl, se, v, uuid, user, pass, captcha。
- 登录成功后会 302 链回 i.sjtu.edu.cn,session cookie 自动落到 jar。
"""
from __future__ import annotations

import logging
import random
import re
import time
from urllib.parse import urljoin

import requests

import config
import session_store

log = logging.getLogger(__name__)

_ocr = None


def _get_ocr():
    global _ocr
    if _ocr is None:
        import ddddocr
        # beta=True 用更新的模型,对小写字母+数字的纯文本验证码识别率更高
        _ocr = ddddocr.DdddOcr(beta=True, show_ad=False)
    return _ocr


class LoginError(RuntimeError):
    pass


_CTX_KEY_RE = re.compile(
    r'(sid|client|returl|se|v|uuid)\s*:\s*"([^"]*)"'
)


def _parse_login_context(html: str) -> dict[str, str]:
    """从 jaccount 登录页 JS 里抽 loginContext 的 6 个字段。"""
    # 限定在 loginContext = { ... } 块内,避免误抓全页 JS 里同名变量
    m = re.search(r"loginContext\s*=\s*\{([^}]+)\}", html, re.DOTALL)
    block = m.group(1) if m else html
    fields = {k: v for k, v in _CTX_KEY_RE.findall(block)}
    return fields


def is_logged_in(session: requests.Session) -> bool:
    """探针:任选一门 tjxkbkk 课程查询,返回 JSON 即为登录有效。

    zzxk 轮次的课程没有单课查询模板(build_query_payload 返回 None),跳过;
    全部课程都是 zzxk 时退回 GET 选课首页(未登录会 302)。
    """
    qp = None
    for kch in config.KCH_QUERIES:
        qp = config.build_query_payload(kch)
        if qp is not None:
            break
    try:
        if qp is None:
            r = session.get(
                config.PAGE_URL,
                headers={"User-Agent": config.USER_AGENT},
                timeout=10,
                allow_redirects=False,
            )
            return r.status_code == 200
        url, payload = qp
        r = session.post(
            url,
            data=payload,
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Referer": config.REFERER,
                "User-Agent": config.USER_AGENT,
            },
            timeout=10,
            allow_redirects=False,
        )
        return r.status_code == 200 and "application/json" in r.headers.get(
            "content-type", ""
        )
    except requests.RequestException:
        return False


def login(session: requests.Session, max_attempts: int = 5) -> None:
    if not config.JACCOUNT_USER or not config.JACCOUNT_PASS:
        raise LoginError("JACCOUNT_USER / JACCOUNT_PASS 未在 .env 中配置")

    session.headers.setdefault("User-Agent", config.USER_AGENT)

    if is_logged_in(session):
        log.info("session 仍有效,跳过登录")
        return

    # session 已确认失效 — 清空所有旧 cookie 再启新登录流程。
    # 不清的话,旧的 JSESSIONID / OAuth state 会让 /jaccountlogin 走异常分支,
    # 导致重登录永远失败(冷启动正常,因为 session 本来就是空的)。
    old_cookies = len(session.cookies)
    if old_cookies:
        log.info("清理 %d 个旧 cookie,重置 session", old_cookies)
        session.cookies.clear()

    # 1. 触发 i.sjtu.edu.cn → jaccount 重定向
    r = session.get(config.JACCOUNT_ENTRY_URL, allow_redirects=True, timeout=20)
    if "jaccount.sjtu.edu.cn" not in r.url:
        raise LoginError(
            f"未跳转到 jaccount,最终 URL: {r.url} "
            f"(status={r.status_code} bytes={len(r.content)})"
        )
    login_page_url = r.url
    ctx = _parse_login_context(r.text)
    required = {"sid", "client", "returl", "se", "uuid"}
    missing = required - ctx.keys()
    if missing:
        raise LoginError(f"jaccount 登录页缺少字段: {missing}")
    log.info("到达 jaccount, uuid=%s", ctx["uuid"][:8])

    ocr = _get_ocr()

    config.CAPTCHA_DEBUG_DIR.mkdir(exist_ok=True)

    for attempt in range(1, max_attempts + 1):
        # 2. 拉验证码图
        cap_resp = session.get(
            config.JACCOUNT_CAPTCHA_URL,
            params={"uuid": ctx["uuid"], "t": str(int(time.time() * 1000))},
            headers={"Referer": login_page_url},
            timeout=10,
        )
        if cap_resp.status_code != 200 or not cap_resp.content:
            raise LoginError(f"拉验证码失败: HTTP {cap_resp.status_code}")

        captcha_text = re.sub(r"\s+", "", str(ocr.classification(cap_resp.content)))
        log.info(
            "尝试 %d/%d, 验证码 OCR: %s (图片 %d 字节)",
            attempt, max_attempts, captcha_text, len(cap_resp.content),
        )
        # debug:把验证码图存盘,方便人工核对 OCR 对不对
        if log.isEnabledFor(logging.DEBUG):
            img_path = config.CAPTCHA_DEBUG_DIR / f"{int(time.time()*1000)}_{captcha_text}.png"
            img_path.write_bytes(cap_resp.content)
            log.debug("验证码图存到 %s", img_path)

        post_data = {
            "sid": ctx["sid"],
            "client": ctx["client"],
            "returl": ctx["returl"],
            "se": ctx["se"],
            "v": ctx.get("v", ""),
            "uuid": ctx["uuid"],
            "user": config.JACCOUNT_USER,
            "pass": config.JACCOUNT_PASS,
            "captcha": captcha_text,
            "lt": "p",  # 必须:p=password 登录;否则服务端误报"验证码错误"
        }

        # 拉验证码到提交之间加 300-700ms 随机延迟,规避"太快"反爬
        time.sleep(random.uniform(0.3, 0.7))

        # 3. 提交凭据 — ulogin 返回 JSON {errno, error, url},不是 302
        ul = session.post(
            config.JACCOUNT_ULOGIN_URL,
            data=post_data,
            headers={
                "Referer": login_page_url,
                "Origin": "https://jaccount.sjtu.edu.cn",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
            },
            allow_redirects=False,
            timeout=20,
        )

        try:
            payload = ul.json()
        except ValueError:
            log.warning(
                "第 %d 次:ulogin 返回非 JSON,status=%s ct=%s body=%s",
                attempt, ul.status_code, ul.headers.get("content-type"),
                ul.text[:300].replace("\n", " "),
            )
            continue

        errno = payload.get("errno")
        error_msg = payload.get("error", "")
        next_url = payload.get("url")

        if errno == 0 and next_url:
            # 4. JS 里的 window.location.href = url —— 手动 GET 完成跳回 i.sjtu.edu.cn
            # 注意 url 可能是相对路径 (/jaccount/jalogin?...),要拼回绝对 URL
            absolute_url = urljoin(config.JACCOUNT_ULOGIN_URL, next_url)
            cb = session.get(absolute_url, allow_redirects=True, timeout=20)
            if is_logged_in(session):
                log.info("登录成功 -> %s", cb.url)
                return
            log.warning(
                "ulogin errno=0 但回跳后 session 仍不可用,回跳 URL: %s",
                cb.url,
            )
            continue

        log.warning(
            "第 %d 次登录失败:errno=%s error=%r",
            attempt, errno, error_msg,
        )
        # 区分密码错与验证码错:密码错没必要继续重试
        if any(kw in str(error_msg).lower() for kw in
               ("password", "credential", "用户名", "密码", "incorrect")):
            raise LoginError(f"用户名或密码错误: {error_msg}")
        if "lock" in str(error_msg).lower() or "锁" in str(error_msg):
            raise LoginError(f"账号被锁定: {error_msg}")
        # 验证码错或其他临时错误 → 重新拉登录页拿新 uuid 再试
        r2 = session.get(config.JACCOUNT_ENTRY_URL, allow_redirects=True, timeout=15)
        new_ctx = _parse_login_context(r2.text)
        if "uuid" in new_ctx and new_ctx["uuid"]:
            ctx = {**ctx, **new_ctx}
            login_page_url = r2.url

    raise LoginError(f"登录失败:连续 {max_attempts} 次验证码识别都没成功")


# 本进程当前用的是哪一代共享会话:force 重登时用它区分"我过期了"和"别人已经重登过"。
_GENERATION_ATTR = "_sjtu_session_generation"


def ensure_session(session: requests.Session, *, force: bool = False,
                   max_attempts: int = 5) -> None:
    """取得可用的教务会话:优先复用进程间共享的 cookie,必要时才真正登录一次。

    教务同一账号只允许一个有效会话,谁登录谁把别人顶掉;但同一份 cookie 可以多个
    客户端并发使用(2026-09-16 实测)。所以监控、全量抓取、换课都走这里,共用一次
    登录,不再互相顶掉 —— 这是"抓取时监控必须停"的替代方案。

    force=True 用于请求已经被判定为会话失效之后:此时若别的进程已经重新登录过
    (代次变了),直接复用它的会话;否则在锁内自己登录一次并写回共享记录。
    """
    mine = getattr(session, _GENERATION_ATTR, None)
    if not force:
        if mine:
            return
        shared = session_store.load(session)
        # 磁盘上的会话可能早就被顶掉了(别的客户端登录过)。不探测就直接用,后续每个
        # 请求都会 302/901 —— 首页读不到 hidden,还会被误判成"不在选课期间"。
        if shared and is_logged_in(session):
            setattr(session, _GENERATION_ATTR, shared)
            return
    with session_store.lock():
        current = session_store.generation()
        if current and current != mine:
            # 别的进程刚登录过 —— 复用它的 cookie,再登一次只会把它顶掉。
            shared = session_store.load(session)
            if is_logged_in(session):
                log.info("复用其他进程刚建立的登录会话")
                setattr(session, _GENERATION_ATTR, shared)
                return
            log.info("其他进程的会话也已失效,重新登录")
        # login() 自带"仍有效就跳过"的探测,所以这里不会白白多登一次。
        login(session, max_attempts=max_attempts)
        setattr(session, _GENERATION_ATTR, session_store.save(session))


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    s = requests.Session()
    login(s)
    print("Cookies:")
    for c in s.cookies:
        print(f"  {c.domain} {c.name} = {c.value[:30]}...")
