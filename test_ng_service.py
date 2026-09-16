"""ng 常驻服务与共用展示逻辑的离线单测(不联网)。"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import ng_logic
import ng_service

ROOT = Path(__file__).resolve().parent

MON_1_2 = "星期一第1-2节{1-16周}"
MON_2_3 = "星期一第2-3节{1-8周}"
TUE_1_2 = "星期二第1-2节{1-16周}"


def chosen(jxb_id, sksj, title="已选课", class_name="01"):
    return {"jxb_id": jxb_id, "title": title, "class_name": class_name, "sksj": sksj}


class GroupConflictMarksTests(unittest.TestCase):
    def test_marks_candidates_that_clash_with_choosed_outside_group(self):
        courses = {"a": {"sksj": MON_2_3}, "b": {"sksj": TUE_1_2}}
        marks = ng_logic.group_conflict_marks(["a", "b"], courses, [chosen("x", MON_1_2, "高数")])
        self.assertEqual(set(marks), {"a"})
        self.assertEqual(marks["a"]["status"], "conflict")
        self.assertEqual(marks["a"]["with"], "高数 - 01")
        self.assertEqual(marks["a"]["detail"], "周一 第2节 (第1周)")

    def test_only_courses_above_held_are_candidates(self):
        courses = {"a": {"sksj": TUE_1_2}, "held": {"sksj": MON_1_2}, "low": {"sksj": MON_2_3}}
        choosed = [chosen("held", MON_1_2), chosen("x", MON_1_2)]
        marks = ng_logic.group_conflict_marks(["a", "held", "low"], courses, choosed)
        self.assertEqual(marks, {})

    def test_choosed_inside_group_is_not_compared(self):
        courses = {"a": {"sksj": MON_1_2}}
        marks = ng_logic.group_conflict_marks(["a", "held"], courses, [chosen("held", MON_1_2)])
        self.assertEqual(marks, {})

    def test_unscheduled_choosed_does_not_occupy_slots(self):
        courses = {"a": {"sksj": MON_1_2}}
        marks = ng_logic.group_conflict_marks(["a"], courses, [chosen("x", "待定")])
        self.assertEqual(marks, {})

    def test_unparseable_schedule_is_unknown(self):
        courses = {"a": {"sksj": "乱码"}}
        marks = ng_logic.group_conflict_marks(["a"], courses, [chosen("x", MON_1_2)])
        self.assertEqual(marks, {"a": {"status": "unknown"}})

    def test_schedule_lines_used_when_sksj_missing(self):
        courses = {"a": {"schedule": [MON_2_3]}}
        marks = ng_logic.group_conflict_marks(["a"], courses, [chosen("x", MON_1_2)])
        self.assertEqual(marks["a"]["status"], "conflict")


class ConflictWarningTests(unittest.TestCase):
    def test_warns_but_lists_conflicts_and_unknowns(self):
        courses = {"a": {"title": "物理", "sksj": MON_2_3}, "b": {"title": "化学", "sksj": ""}}
        text = ng_logic.conflict_warning(["a", "b"], [], courses, [chosen("x", MON_1_2, "高数")])
        self.assertIn("物理 与已选 高数 - 01", text)
        self.assertIn("化学", text)
        self.assertTrue(text.endswith("已加入方案，可继续保存。"))

    def test_no_warning_without_conflict(self):
        courses = {"a": {"title": "物理", "sksj": TUE_1_2}}
        self.assertIsNone(ng_logic.conflict_warning(["a"], [], courses, [chosen("x", MON_1_2)]))

    def test_adding_a_choosed_course_never_warns(self):
        self.assertIsNone(ng_logic.conflict_warning(["x"], [], {}, [chosen("x", MON_1_2)]))


class MergePriorityTests(unittest.TestCase):
    def test_targets_before_choosed(self):
        self.assertEqual(
            ng_logic.merge_priority_ids(["a", "held"], ["b", "held2", "a"], {"held", "held2"}),
            ["a", "b", "held", "held2"],
        )


class ParseLogLineTests(unittest.TestCase):
    def test_python_logging_line(self):
        entry = ng_logic.parse_log_line("monitor", "2026-09-16 12:55:01,123 WARNING [zzxk] 非 JSON")
        self.assertEqual(entry, {"time": "12:55:01", "level": "warn", "source": "zzxk", "message": "非 JSON"})

    def test_change_record_json(self):
        line = '2026-09-16 12:00:00 {"kind": "changes", "kcmc": "物理", "jxbmc": "01", "changes": {"jxbxzrs": [10, 11]}}'
        entry = ng_logic.parse_log_line("changes", line)
        self.assertEqual(entry["message"], "[变动] 01 物理 班选中 10→11")

    def test_swap_fatal_is_error(self):
        entry = ng_logic.parse_log_line("changes", '{"kind": "swap_result", "ok": false, "status": "FATAL_LOST", "kcmc": "物理"}')
        self.assertEqual(entry["level"], "error")

    def test_plain_text_heuristics(self):
        self.assertEqual(ng_logic.parse_log_line("x", "exit=0", "01:02:03")["level"], "info")
        self.assertEqual(ng_logic.parse_log_line("x", "exit=3")["level"], "error")
        self.assertEqual(ng_logic.parse_log_line("x", "$ python monitor.py")["level"], "debug")
        self.assertEqual(ng_logic.parse_log_line("x", "登录失败")["level"], "error")
        self.assertEqual(ng_logic.parse_log_line("x", "hello", "01:02:03")["time"], "01:02:03")


class BootstrapNoticeTests(unittest.TestCase):
    def test_structured_result(self):
        result = ng_logic.parse_bootstrap_result('[bootstrap-result] {"ok": false, "reason": "closed", "message": "未开放"}')
        self.assertEqual(
            ng_logic.bootstrap_failure_notice(result, 3),
            {"title": "教务网站选课未开放", "message": "未开放"},
        )

    def test_generic_notice_without_result(self):
        notice = ng_logic.bootstrap_failure_notice(None, None, "读取当前学期")
        self.assertEqual(notice["title"], "读取当前学期失败")
        self.assertIn("exit=-", notice["message"])

    def test_garbage_result_ignored(self):
        self.assertIsNone(ng_logic.parse_bootstrap_result("[bootstrap-result] {oops"))


class ProcessManagerTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        patcher = patch.object(ng_service, "send", side_effect=self.events.append)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.logs = ng_service.LogBook(lambda: Path(self.tmp.name) / "changes.log")
        self.manager = ng_service.ProcessManager(self.logs, lambda: Path(self.tmp.name))

    def wait_exit(self, task, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            for message in self.events:
                if message.get("event") == "process.exited" and message["data"]["task"] == task:
                    return message["data"]
            time.sleep(0.05)
        self.fail(f"{task} did not exit")

    def fake_command(self, code):
        script = (
            "print('中文输出');"
            "print('[bootstrap-result] ' + '{\"ok\": false, \"reason\": \"closed\", \"message\": \"未开放\"}');"
            f"raise SystemExit({code})"
        )
        return lambda _script, _args: [sys.executable, "-c", script]

    def test_failed_bootstrap_emits_output_and_notice(self):
        with patch.object(ng_service, "backend_command", self.fake_command(3)):
            self.assertEqual(self.manager.start("bootstrap", [], False), ["bootstrap"])
            data = self.wait_exit("bootstrap")
        self.assertEqual(data["code"], 3)
        self.assertEqual(data["notice"]["title"], "教务网站选课未开放")
        outputs = [m["data"]["entry"]["message"] for m in self.events if m.get("event") == "process.output"]
        self.assertIn("中文输出", outputs)
        self.assertEqual(self.manager.running(), [])
        messages = [entry["message"] for entry in self.logs.query()["entries"]]
        self.assertEqual(messages[-1], "exit=3")

    def test_unknown_task_rejected(self):
        with self.assertRaises(ng_service.RpcError):
            self.manager.start("rm -rf", [], False)

    def test_stop_suppresses_failure_notice(self):
        sleeper = lambda _s, _a: [sys.executable, "-c", "import time; print('up', flush=True); time.sleep(60)"]
        with patch.object(ng_service, "backend_command", sleeper):
            self.manager.start("bootstrap", [], False)
            with self.assertRaises(ng_service.RpcError):
                self.manager.start("bootstrap", [], False)
            self.manager.stop("bootstrap")
            data = self.wait_exit("bootstrap")
        self.assertTrue(data["stopped"])
        self.assertNotIn("notice", data)


class LogBookTests(unittest.TestCase):
    def test_query_merges_persisted_and_runtime_with_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_file = Path(tmp) / "changes.log"
            log_file.write_text('2026-09-16 10:00:00 {"kind": "spot_open", "kcmc": "物理", "msg": "1 空位"}\n', "utf-8")
            book = ng_service.LogBook(lambda: log_file)
            book.add("monitor", "2026-09-16 10:00:01 ERROR 登录失败")
            book.add("monitor", "普通输出")
            result = book.query()
            self.assertEqual(result["counts"], {"all": 3, "info": 1, "warn": 1, "error": 1, "debug": 0})
            self.assertEqual(book.query(level="error")["entries"][0]["message"], "登录失败")
            self.assertEqual(len(book.query(text="物理")["entries"]), 1)
            self.assertEqual(len(book.query(limit=1)["entries"]), 1)


class ServiceProtocolTests(unittest.TestCase):
    """真正起一个 ng_service 子进程,走 stdio 协议。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        data = Path(self.tmp.name)
        (data / "user_settings.json").write_text(json.dumps({
            "term": {"xkxnm": "2026", "xkxqm": "3"},
            "terms": {"2026-3": {"priority_groups": {"物理": {"is_pe": False, "priority": ["a", "held"]}}}},
        }, ensure_ascii=False), "utf-8")
        term = data / "terms" / "2026-3"
        term.mkdir(parents=True)
        (term / "catalog.json").write_text(json.dumps({
            "courses": [{
                "kch": "PHY1", "kcmc": "大学物理", "kch_id": "K1", "kklxdm": "01",
                "classes": [
                    {"jxb_id": "a", "jxbmc": "物理-01", "sksj": MON_2_3, "jsxx": "1/张三/教授"},
                    {"jxb_id": "held", "jxbmc": "物理-02", "sksj": TUE_1_2},
                    {"jxb_id": "b", "jxbmc": "物理-03", "sksj": MON_1_2},
                ],
            }],
            "choosed": [
                {"jxb_id": "held", "kcmc": "大学物理", "jxbmc": "物理-02", "sksj": TUE_1_2},
                {"jxb_id": "x", "kcmc": "高等数学", "jxbmc": "数学-01", "sksj": MON_1_2},
            ],
        }, ensure_ascii=False), "utf-8")
        env = {**os.environ, "SJTU_MONITOR_DATA_DIR": str(data), "PYTHONUTF8": "1"}
        env.pop("SJTU_MONITOR_RELEASE", None)
        self.proc = subprocess.Popen(
            [sys.executable, str(ROOT / "ng_service.py")],
            cwd=str(ROOT), env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self.addCleanup(self._close)
        self.messages = []
        self.lock = threading.Condition()
        threading.Thread(target=self._read, daemon=True).start()
        self.next_id = 0

    def _close(self):
        if self.proc.poll() is None:
            self.proc.stdin.close()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.proc.stdout.close()
        self.proc.stderr.close()

    def _read(self):
        for raw in self.proc.stdout:
            message = json.loads(raw.decode("utf-8"))
            with self.lock:
                self.messages.append(message)
                self.lock.notify_all()

    def wait_for(self, predicate, timeout=20):
        deadline = time.time() + timeout
        with self.lock:
            while True:
                for message in self.messages:
                    if predicate(message):
                        return message
                remaining = deadline - time.time()
                if remaining <= 0:
                    stderr = self.proc.stderr.read1(65536).decode("utf-8", "replace") if self.proc.poll() is not None else ""
                    self.fail(f"timeout; got {self.messages!r} {stderr}")
                self.lock.wait(remaining)

    def call(self, method, params=None):
        self.next_id += 1
        request_id = self.next_id
        payload = json.dumps({"id": request_id, "method": method, "params": params or {}}, ensure_ascii=False)
        self.proc.stdin.write(payload.encode("utf-8") + b"\n")
        self.proc.stdin.flush()
        return self.wait_for(lambda m: m.get("id") == request_id)

    def test_protocol_round_trip(self):
        ready = self.wait_for(lambda m: m.get("event") == "ready")
        self.assertEqual(ready["data"]["protocol"], 1)

        snapshot = self.call("snapshot")["result"]
        self.assertNotIn("logs", snapshot)
        self.assertEqual(snapshot["active_term"], "2026-3")
        group = snapshot["groups"][0]
        self.assertEqual(group["conflict_count"], 1)
        self.assertEqual(group["conflicts"]["a"]["with"], "高等数学 - 数学-01")

        evaluated = self.call("groups.evaluate", {"groups": [{"name": "新", "priority": ["b", "a"]}]})["result"]
        self.assertEqual(evaluated["groups"][0]["held"], None)
        self.assertEqual(set(evaluated["groups"][0]["conflicts"]), {"a", "b"})

        added = self.call("groups.add_courses", {"priority": ["a", "held"], "added": ["b", "a"]})["result"]
        self.assertEqual(added["priority"], ["a", "b", "held"])
        self.assertEqual(added["added"], ["b"])
        self.assertIn("大学物理 与已选 高等数学", added["warning"])

        error = self.call("nope")["error"]
        self.assertEqual(error["code"], "method_not_found")
        bad = self.call("process.start", {"task": "evil"})["error"]
        self.assertEqual(bad["code"], "invalid_params")
        self.assertEqual(self.call("logs.query")["result"]["counts"]["all"], 0)

    def test_settings_changed_by_another_process_are_reloaded(self):
        self.wait_for(lambda m: m.get("event") == "ready")
        self.assertEqual(self.call("snapshot")["result"]["site_term"], None)
        settings_file = Path(self.tmp.name) / "user_settings.json"
        data = json.loads(settings_file.read_text("utf-8"))
        data["site_term"] = {"xkxnm": "2026", "xkxqm": "3", "label": "2026-2027 秋", "zzxk_open": True}
        time.sleep(0.01)
        settings_file.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
        os.utime(settings_file, (time.time() + 5, time.time() + 5))
        site = self.call("snapshot")["result"]["site_term"]
        self.assertTrue(site["matches_active"])
        self.wait_for(lambda m: m.get("event") == "state.changed" and "user_settings" in m["data"]["files"])

    def test_stdin_close_exits_cleanly(self):
        self.wait_for(lambda m: m.get("event") == "ready")
        self.proc.stdin.close()
        self.assertEqual(self.proc.wait(timeout=10), 0)


if __name__ == "__main__":
    unittest.main()
