"""跨进程共享的教务登录会话(cookie 落盘 + 登录锁)。

2026-09-16 联网实测的两条事实决定了这里的设计:
  1. 同一个 JAccount 同时只有一个有效会话 —— 谁重新登录一次,别人的会话立刻作废,
     之后 ajax 接口一律回 status=901(空响应体),页面请求回 302;
  2. 但把同一份 cookie 交给多个客户端**并发请求**完全正常(实测 6 次交叉请求全部成功),
     就像浏览器开两个标签页。

所以监控与全量抓取要并行,唯一的要求是"整个账号只登录一次、大家共用 cookie"。
本模块提供:cookie 读写 + 跨进程互斥锁 + 代次(generation)判断 —— 代次用来区分
"我的会话过期了"和"别的进程已经重新登录过了",后者直接复用即可,不能再登一次
把对方顶掉(那正是 2026-09-16 中午目录被抓残的原因)。

cookie 等同于登录凭据,所以文件按 0600 写,并且不入库(见 .gitignore)。
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

import requests

import config

log = logging.getLogger("session")

_COOKIE_FIELDS = ("name", "value", "domain", "path")


def session_file() -> Path:
    # 会话是账号级的,不按学期分区;调用时取值,便于测试替换 DATA_DIR。
    return config.DATA_DIR / "session.json"


def lock_file() -> Path:
    return config.DATA_DIR / "session.lock"


def _acquire(handle, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            if sys.platform.startswith("win"):
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"等待登录锁超时({timeout}s)")
            time.sleep(0.2)


def _release(handle) -> None:
    try:
        if sys.platform.startswith("win"):
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


@contextlib.contextmanager
def lock(timeout: float = 180.0):
    """跨进程登录锁:同一时刻只允许一个进程走登录流程。

    锁不可用时(只读目录等异常)不阻断调用方 —— 退化成各自登录,行为与加锁前一致。
    """
    path = lock_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(path, "a+b")
    except OSError as e:
        log.warning("登录锁不可用,退化为不加锁: %s", e)
        yield
        return
    try:
        _acquire(handle, timeout)
        yield
    finally:
        _release(handle)
        handle.close()


def _read() -> dict:
    try:
        data = json.loads(session_file().read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def generation() -> str | None:
    """当前共享会话的代次;每次真正登录都会换一个新值。"""
    return _read().get("generation") or None


def load(session: requests.Session) -> str | None:
    """把共享 cookie 注入 session,返回其代次;没有可用记录时返回 None。"""
    data = _read()
    cookies = data.get("cookies")
    if not data.get("generation") or not isinstance(cookies, list) or not cookies:
        return None
    if (data.get("user") or "") != (config.JACCOUNT_USER or ""):
        # 账号换过了:旧 cookie 仍可能通过"是否已登录"的探测,但那是别人的会话。
        log.info("共享会话属于账号 %s,与当前配置不符,忽略", data.get("user"))
        return None
    session.cookies.clear()
    for c in cookies:
        if not isinstance(c, dict) or not c.get("name"):
            continue
        session.cookies.set(
            c["name"], c.get("value") or "",
            domain=c.get("domain") or "", path=c.get("path") or "/",
        )
    session.headers.setdefault("User-Agent", config.USER_AGENT)
    return data["generation"]


def save(session: requests.Session) -> str:
    """把本次登录得到的 cookie 写成新的共享会话,返回新代次。"""
    gen = uuid.uuid4().hex
    payload = {
        "generation": gen,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "user": config.JACCOUNT_USER,
        "cookies": [
            {field: getattr(c, field, None) for field in _COOKIE_FIELDS}
            for c in session.cookies
        ],
    }
    path = session_file()
    tmp = path.with_suffix(".json.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")
        os.chmod(tmp, 0o600)
        config.replace_atomic(tmp, path)
    except OSError as e:
        # 存不下只是失去"共享"这层优化,本进程自己的 session 依然可用。
        log.warning("共享会话写入失败,其他进程无法复用本次登录: %s", e)
    return gen


def clear() -> None:
    """丢弃共享会话记录(凭据变更/退出登录时用)。"""
    try:
        session_file().unlink()
    except OSError:
        pass
