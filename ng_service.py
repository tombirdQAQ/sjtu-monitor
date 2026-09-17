"""ng 原生客户端的常驻后端服务(协议 v1,见 ng/DESIGN.md)。

    python ng_service.py            # 源码模式
    sjtu-backend ng_service.py      # 打包模式(backend_entry 分发)

stdin/stdout 上按行交换 UTF-8 JSON。stdout 只用于协议:启动时复制一份原始 stdout
句柄专门写协议,再把 sys.stdout 指向 stderr,防止任何模块的 print 把协议流写坏。

- 请求按到达顺序在单个工作线程里串行执行(config 模块级状态不是线程安全的);
- 监控/抓取子进程的输出由各自的读取线程转成 process.output 事件;
- 状态文件的 mtime 变化由监听线程推送 state.changed,客户端据此重取快照。
stdin 关闭即退出,并结束本服务启动的全部子进程。
"""
from __future__ import annotations

import collections
import json
import os
import platform
import queue
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

PROTOCOL_VERSION = 1
ROOT = Path(__file__).resolve().parent
RUNTIME_LOG_LIMIT = 500
PERSISTED_LOG_LINES = 300
WATCH_INTERVAL = 1.5

# 协议输出通道要在导入业务模块之前建立:它们导入时可能 print。
_protocol_out = None
_write_lock = threading.Lock()


def _open_protocol_stream() -> None:
    """接管原始 stdout 专用于协议,其余 print 改写到 stderr。

    不用 os.dup 另开文件描述符:PyInstaller 窗口化(console=False)的 Windows sidecar 里,
    对复制出来的管道描述符写入会报 EINVAL;原 stdout 对象本身可以正常写(Tauri 版一直如此)。
    """
    global _protocol_out
    if _protocol_out is not None:
        return
    stream = sys.stdout
    if stream is None:
        raise RuntimeError("stdout 不可用,无法建立协议通道")
    try:
        stream.reconfigure(encoding="utf-8", errors="strict", newline="\n")
    except (AttributeError, ValueError):
        pass
    _protocol_out = stream
    sys.stdout = sys.stderr if sys.stderr is not None else open(os.devnull, "w", encoding="utf-8")


def send(message: dict[str, Any]) -> None:
    line = json.dumps(message, ensure_ascii=False, separators=(",", ":"), default=str)
    with _write_lock:
        assert _protocol_out is not None
        _protocol_out.write(line + "\n")
        _protocol_out.flush()


def emit_event(name: str, data: dict[str, Any]) -> None:
    send({"event": name, "data": data})


class RpcError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def now_time() -> str:
    return datetime.now().strftime("%H:%M:%S")


def is_release_mode() -> bool:
    return os.getenv("SJTU_MONITOR_RELEASE", "").strip() == "1"


# ------------------------------------------------------------------ 子进程 ---

TASKS: dict[str, tuple[str, list[str]]] = {
    "once": ("monitor.py", ["--once"]),
    "monitor": ("monitor.py", []),
    "bootstrap": ("bootstrap.py", []),
    "ratings-all": ("bootstrap.py", ["--fetch-ratings-all"]),
    "detect-term": ("bootstrap.py", ["--detect-term"]),
}

# 演示模式下拒绝的方法:会联网或写盘。groups.save 在演示模式下只改内存,不在此列。
DEMO_BLOCKED_METHODS = {
    "settings.save", "settings.test_email", "onboarding.complete", "term.switch",
    "autoswap.set", "process.start",
}
DEMO_BLOCKED_MESSAGE = "演示模式：联网、监控与写入操作已禁用，退出演示后可用"

# 这些任务输出 [bootstrap-result] 结构化结果行,非 0 退出时据此生成提示。
NOTICE_ACTIONS = {
    "bootstrap": "获取全量课程",
    "detect-term": "读取当前学期",
    "ratings-all": "获取全部评价",
}


def backend_command(script: str, args: list[str]) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, script, *args]
    return [sys.executable, "-u", str(ROOT / script), *args]


class ProcessManager:
    def __init__(self, logs: "LogBook", data_dir: Callable[[], Path]) -> None:
        self._logs = logs
        self._data_dir = data_dir
        self._lock = threading.Lock()
        self._children: dict[str, subprocess.Popen] = {}
        self._results: dict[str, dict[str, Any]] = {}
        self._stopping: set[str] = set()

    def running(self) -> list[str]:
        with self._lock:
            return sorted(self._children)

    def start(self, task: str, extra_args: list[str], debug: bool) -> list[str]:
        if task not in TASKS:
            raise RpcError("invalid_params", f"未知任务: {task}")
        script, args = TASKS[task]
        args = [*args, *extra_args]
        if debug and not is_release_mode():
            args.append("--debug")
        env = os.environ.copy()
        env.update({
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
            "SJTU_MONITOR_DATA_DIR": str(self._data_dir()),
        })
        kwargs: dict[str, Any] = {}
        if os.name == "nt":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        with self._lock:
            if task in self._children:
                raise RpcError("already_running", f"{task} 已在运行")
            try:
                child = subprocess.Popen(
                    backend_command(script, args),
                    cwd=str(self._data_dir()),
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    **kwargs,
                )
            except OSError as exc:
                raise RpcError("spawn_failed", f"无法启动 {task}: {exc}") from exc
            self._children[task] = child
            self._results.pop(task, None)
        self._logs.add(task, f"$ python {script} {' '.join(args)}".rstrip())
        threading.Thread(target=self._pump, args=(task, child), daemon=True).start()
        emit_event("processes", {"running": self.running()})
        return self.running()

    def stop(self, task: str) -> list[str]:
        with self._lock:
            child = self._children.get(task)
            if child is not None:
                self._stopping.add(task)
        if child is not None:
            _terminate(child)
        return self.running()

    def stop_all(self) -> None:
        with self._lock:
            children = list(self._children.items())
            self._stopping.update(task for task, _ in children)
        for _, child in children:
            _terminate(child)

    def _pump(self, task: str, child: subprocess.Popen) -> None:
        import ng_logic

        assert child.stdout is not None
        for raw in iter(child.stdout.readline, b""):
            text = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if not text:
                continue
            result = ng_logic.parse_bootstrap_result(text)
            if result is not None:
                with self._lock:
                    self._results[task] = result
            entry = self._logs.add(task, text)
            emit_event("process.output", {"task": task, "entry": entry})
        child.stdout.close()
        code = child.wait()
        with self._lock:
            self._children.pop(task, None)
            result = self._results.pop(task, None)
            stopped = task in self._stopping
            self._stopping.discard(task)
        self._logs.add(task, f"exit={code}")
        data: dict[str, Any] = {"task": task, "code": code, "stopped": stopped}
        if task in NOTICE_ACTIONS and code != 0 and not stopped:
            data["notice"] = ng_logic.bootstrap_failure_notice(result, code, NOTICE_ACTIONS[task])
        if result is not None:
            data["result"] = result
        emit_event("process.exited", data)
        emit_event("processes", {"running": self.running()})


def _terminate(child: subprocess.Popen) -> None:
    if child.poll() is not None:
        return
    try:
        child.terminate()
        child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        child.kill()
    except OSError:
        pass


# -------------------------------------------------------------------- 日志 ---


class LogBook:
    """运行期日志环形缓冲 + changes.log 尾部(按 mtime 缓存解析结果)。"""

    def __init__(self, log_file: Callable[[], Path]) -> None:
        self._log_file = log_file
        self._runtime: collections.deque[dict[str, str]] = collections.deque(maxlen=RUNTIME_LOG_LIMIT)
        self._lock = threading.Lock()
        self._persisted_key: tuple[str, float] | None = None
        self._persisted: list[dict[str, str]] = []

    def add(self, source: str, text: str) -> dict[str, str]:
        import ng_logic

        entry = ng_logic.parse_log_line(source, text, now_time())
        with self._lock:
            self._runtime.append(entry)
        return entry

    def _persisted_entries(self) -> list[dict[str, str]]:
        import ng_logic

        path = self._log_file()
        try:
            key = (str(path), path.stat().st_mtime)
        except OSError:
            return []
        if key != self._persisted_key:
            lines = path.read_text("utf-8", errors="replace").splitlines()[-PERSISTED_LOG_LINES:]
            self._persisted = [ng_logic.parse_log_line("changes", line) for line in lines]
            self._persisted_key = key
        return self._persisted

    def query(self, level: str = "all", text: str = "", limit: int = 350) -> dict[str, Any]:
        with self._lock:
            runtime = list(self._runtime)
        return filter_log_entries([*self._persisted_entries(), *runtime], level, text, limit)


def filter_log_entries(lines: list[dict[str, str]], level: str = "all", text: str = "", limit: int = 350) -> dict[str, Any]:
    needle = text.strip().casefold()
    if needle:
        lines = [line for line in lines if needle in f"{line['source']} {line['message']}".casefold()]
    counts = {"all": len(lines), "info": 0, "warn": 0, "error": 0, "debug": 0}
    for line in lines:
        counts[line["level"]] = counts.get(line["level"], 0) + 1
    if level and level != "all":
        lines = [line for line in lines if line["level"] == level]
    if limit > 0:
        lines = lines[-limit:]
    return {"entries": lines, "counts": counts}


# ---------------------------------------------------------------- 文件监听 ---


class StateWatcher(threading.Thread):
    def __init__(self, files: Callable[[], dict[str, Path]]) -> None:
        super().__init__(daemon=True)
        self._files = files
        self._mtimes: dict[str, float | None] = {}
        self._stop = threading.Event()

    @staticmethod
    def _mtime(path: Path) -> float | None:
        try:
            return path.stat().st_mtime
        except OSError:
            return None

    def poll(self) -> list[str]:
        changed = []
        for name, path in self._files().items():
            key = f"{name}:{path}"
            current = self._mtime(path)
            if key in self._mtimes and self._mtimes[key] != current:
                changed.append(name)
            self._mtimes[key] = current
        return changed

    def run(self) -> None:
        self.poll()
        while not self._stop.wait(WATCH_INTERVAL):
            try:
                changed = self.poll()
            except Exception:
                continue
            if changed:
                emit_event("state.changed", {"files": changed})

    def stop(self) -> None:
        self._stop.set()


# ------------------------------------------------------------------ 服务 ---


class Service:
    def __init__(self) -> None:
        import config

        self.config = config
        self.demo = None  # ng_demo.DemoState:演示模式下的内存数据
        self._settings_mtime = self._file_mtime(config.USER_SETTINGS_FILE)
        self.logs = LogBook(lambda: self.config.LOG_FILE)
        self.processes = ProcessManager(self.logs, lambda: self.config.DATA_DIR)
        self.methods: dict[str, Callable[[dict[str, Any]], Any]] = {
            "hello": self.hello,
            "snapshot": self.snapshot,
            "groups.evaluate": self.groups_evaluate,
            "groups.add_courses": self.groups_add_courses,
            "groups.save": self.groups_save,
            "settings.save": self.settings_save,
            "settings.test_email": lambda _p: self._backend().test_email(),
            "onboarding.complete": lambda _p: self._backend().complete_onboarding(),
            "term.switch": self.term_switch,
            "autoswap.set": self.autoswap_set,
            "process.start": self.process_start,
            "process.stop": self.process_stop,
            "process.list": lambda _p: {"running": self.processes.running()},
            "logs.query": self.logs_query,
            "demo.enter": self.demo_enter,
            "demo.exit": self.demo_exit,
        }

    @staticmethod
    def _file_mtime(path: Path) -> float | None:
        try:
            return path.stat().st_mtime
        except OSError:
            return None

    @staticmethod
    def _backend():
        import gui_backend

        return gui_backend

    def watched_files(self) -> dict[str, Path]:
        c = self.config
        return {
            "user_settings": c.USER_SETTINGS_FILE,
            "state": c.STATE_FILE,
            "swap_state": c.SWAP_STATE_FILE,
            "catalog": c.CATALOG_FILE,
            "seat_details": c.SEAT_DETAILS_FILE,
            "ratings": c.RATINGS_FILE,
            "changes_log": c.LOG_FILE,
        }

    def refresh_config(self) -> None:
        """子进程(bootstrap 记录网站学期/切换学期)会改写 user_settings.json,常驻进程需重读。"""
        current = self._file_mtime(self.config.USER_SETTINGS_FILE)
        if current == self._settings_mtime:
            return
        self.config.USER_SETTINGS = self.config.load_user_settings()
        self.config._apply_settings(self.config.USER_SETTINGS)
        self._settings_mtime = current

    def _mark_settings_written(self) -> None:
        self._settings_mtime = self._file_mtime(self.config.USER_SETTINGS_FILE)

    def handle(self, method: str, params: dict[str, Any]) -> Any:
        handler = self.methods.get(method)
        if handler is None:
            raise RpcError("method_not_found", f"未知方法: {method}")
        if self.demo is not None and method in DEMO_BLOCKED_METHODS:
            raise RpcError("demo_mode", DEMO_BLOCKED_MESSAGE)
        self.refresh_config()
        try:
            return handler(params)
        finally:
            self._mark_settings_written()

    # -- 方法实现 --

    def hello(self, _params: dict[str, Any]) -> dict[str, Any]:
        return {
            "protocol": PROTOCOL_VERSION,
            "version": _app_version(),
            "release_mode": is_release_mode(),
            "data_dir": str(self.config.DATA_DIR),
            "platform": platform.system().lower(),
            "running": self.processes.running(),
            "demo": self.demo is not None,
        }

    def demo_enter(self, _params: dict[str, Any]) -> dict[str, Any]:
        import ng_demo

        if self.demo is None:
            self.demo = ng_demo.DemoState()
        return {"ok": True, "demo": True}

    def demo_exit(self, _params: dict[str, Any]) -> dict[str, Any]:
        self.demo = None
        return {"ok": True, "demo": False}

    def _conflict_context(self, model=None):
        if self.demo is not None:
            return self.demo, self.demo.courses_by_id, self.demo.choosed
        backend = self._backend()
        model = model or backend.CourseModel()
        courses_by_id = {
            jxb_id: {**row, "title": backend.course_title(row)}
            for jxb_id, row in model.rows_by_id.items()
        }
        choosed = []
        for row in model.catalog.get("choosed", []):
            if not isinstance(row, dict) or not row.get("jxb_id"):
                continue
            merged = {**row, **model.rows_by_id.get(row["jxb_id"], {})}
            choosed.append({
                "jxb_id": row["jxb_id"],
                "title": backend.course_title(merged),
                "class_name": backend.class_suffix(merged),
                "sksj": row.get("sksj"),
            })
        return model, courses_by_id, choosed

    def snapshot(self, _params: dict[str, Any]) -> dict[str, Any]:
        import ng_logic

        if self.demo is not None:
            data = self.demo.snapshot()
            data["release_mode"] = is_release_mode()
            data["demo"] = True
            return data
        data = self._backend().build_snapshot()
        data.pop("logs", None)
        data["demo"] = False
        courses_by_id = {row["jxb_id"]: row for row in data["courses"]}
        for group in data["groups"]:
            marks = ng_logic.group_conflict_marks(group["priority"], courses_by_id, data["choosed"])
            group["conflicts"] = marks
            group["conflict_count"] = len(marks)
        data["running"] = self.processes.running()
        data["release_mode"] = is_release_mode()
        return data

    def groups_evaluate(self, params: dict[str, Any]) -> dict[str, Any]:
        import ng_logic

        groups = params.get("groups")
        if not isinstance(groups, list):
            raise RpcError("invalid_params", "groups 必须是数组")
        model, courses_by_id, choosed = self._conflict_context()
        chosen_ids = {row["jxb_id"] for row in choosed}
        out = []
        for group in groups:
            priority = [str(jxb_id) for jxb_id in group.get("priority", []) if jxb_id]
            held = next((jxb_id for jxb_id in priority if jxb_id in chosen_ids), None)
            marks = ng_logic.group_conflict_marks(priority, courses_by_id, choosed)
            out.append({
                "name": group.get("name"),
                "held": held,
                "held_label": model.label_for(held),
                "conflicts": marks,
                "conflict_count": len(marks),
            })
        return {"groups": out}

    def groups_add_courses(self, params: dict[str, Any]) -> dict[str, Any]:
        import ng_logic

        priority = [str(jxb_id) for jxb_id in params.get("priority", []) if jxb_id]
        requested = [str(jxb_id) for jxb_id in params.get("added", []) if jxb_id]
        added = [jxb_id for jxb_id in dict.fromkeys(requested) if jxb_id not in priority]
        if not added:
            return {"priority": priority, "added": [], "warning": None}
        _model, courses_by_id, choosed = self._conflict_context()
        chosen_ids = {row["jxb_id"] for row in choosed}
        return {
            "priority": ng_logic.merge_priority_ids(priority, added, chosen_ids),
            "added": added,
            "warning": ng_logic.conflict_warning(added, priority, courses_by_id, choosed),
        }

    def groups_save(self, params: dict[str, Any]) -> dict[str, Any]:
        if self.demo is not None:
            groups = params.get("groups")
            if not isinstance(groups, dict):
                raise RpcError("invalid_params", "groups 必须是对象")
            self.demo.groups = {
                str(name): {"is_pe": bool(g.get("is_pe")), "priority": [str(i) for i in g.get("priority", []) if i]}
                for name, g in groups.items() if str(name).strip()
            }
            return {"ok": True, "warnings": ["演示模式：方案只在本次演示中生效，不会写入磁盘"],
                    "duplicates": {}, "unresolved": [], "course_count": len(self.demo.groups)}
        return self._backend().save_groups(params)

    def settings_save(self, params: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._backend().save_settings(params)
        except (TypeError, ValueError) as exc:
            raise RpcError("invalid_params", str(exc)) from exc

    def term_switch(self, params: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._backend().switch_term(params)
        except ValueError as exc:
            raise RpcError("invalid_params", str(exc)) from exc

    def autoswap_set(self, params: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._backend().set_auto_swap(params)
        except ValueError as exc:
            raise RpcError("invalid_params", str(exc)) from exc

    def process_start(self, params: dict[str, Any]) -> dict[str, Any]:
        task = str(params.get("task") or "")
        extra: list[str] = []
        if task == "bootstrap" and params.get("adopt_site_term"):
            extra.append("--adopt-site-term")
        running = self.processes.start(task, extra, bool(params.get("debug")))
        return {"ok": True, "running": running}

    def process_stop(self, params: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "running": self.processes.stop(str(params.get("task") or ""))}

    def logs_query(self, params: dict[str, Any]) -> dict[str, Any]:
        try:
            limit = int(params.get("limit", 350))
        except (TypeError, ValueError):
            limit = 350
        if self.demo is not None:
            return filter_log_entries(self.demo.log_entries(), str(params.get("level") or "all"),
                                      str(params.get("query") or ""), limit)
        return self.logs.query(
            level=str(params.get("level") or "all"),
            text=str(params.get("query") or ""),
            limit=limit,
        )


def _app_version() -> str:
    try:
        return json.loads((ROOT / "package.json").read_text("utf-8")).get("version", "")
    except Exception:
        return ""


def _error_payload(exc: BaseException) -> dict[str, str]:
    if isinstance(exc, RpcError):
        return {"code": exc.code, "message": str(exc)}
    traceback.print_exc(file=sys.stderr)
    return {"code": "internal", "message": str(exc) or exc.__class__.__name__}


def serve(stdin=None) -> int:
    _open_protocol_stream()
    stdin = stdin or sys.stdin.buffer
    try:
        service = Service()
    except Exception as exc:  # 配置损坏等致命错误也要按协议报给客户端
        send({"event": "fatal", "data": _error_payload(exc)})
        return 1
    requests: "queue.Queue[dict[str, Any] | None]" = queue.Queue()

    def worker() -> None:
        while True:
            request = requests.get()
            if request is None:
                return
            request_id = request.get("id")
            try:
                params = request.get("params") or {}
                if not isinstance(params, dict):
                    raise RpcError("invalid_params", "params 必须是对象")
                result = service.handle(str(request.get("method") or ""), params)
                send({"id": request_id, "result": result})
            except BaseException as exc:
                send({"id": request_id, "error": _error_payload(exc)})

    worker_thread = threading.Thread(target=worker, daemon=True)
    worker_thread.start()
    watcher = StateWatcher(service.watched_files)
    watcher.start()
    emit_event("ready", service.hello({}))

    for raw in iter(stdin.readline, b""):
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("request must be an object")
        except ValueError as exc:
            send({"id": None, "error": {"code": "parse_error", "message": str(exc)}})
            continue
        requests.put(request)

    requests.put(None)
    worker_thread.join(timeout=10)
    watcher.stop()
    service.processes.stop_all()
    return 0


def main(argv: list[str] | None = None) -> int:
    return serve()


if __name__ == "__main__":
    raise SystemExit(main())
