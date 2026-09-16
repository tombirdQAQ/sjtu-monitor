"""monitor 实际已选同步 + 冲突规则 + 自动换课的离线单测(不联网,swap/抓取全部 mock)。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config
import monitor
import timetable

MON_12 = "星期一第1-2节{1-16周}"
MON_23 = "星期一第2-3节{1-16周}"
TUE_12 = "星期二第1-2节{1-16周}"
WED_12 = "星期三第1-2节{1-16周}"

GROUPS = {
    "英语": {"is_pe": False, "priority": ["en-a", "en-b", "en-held", "en-low"]},
    "物理": {"is_pe": False, "priority": ["ph-a", "ph-held"]},
}


def row(jxb_id, sksj, sel="10", cap="30"):
    return {"jxb_id": jxb_id, "kcmc": jxb_id, "jxbmc": f"{jxb_id}-班",
            "sksj": sksj, "jxbxzrs": sel, "jxbrl": cap}


def spot(jxb_id):
    return {"kind": "spot_open", "jxb_id": jxb_id, "jxbmc": jxb_id, "kcmc": jxb_id}


class _TempFiles(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.catalog_file = root / "catalog.json"
        self.swap_state_file = root / "swap_state.json"
        patches = [
            patch.object(config, "CATALOG_FILE", self.catalog_file),
            patch.object(config, "SWAP_STATE_FILE", self.swap_state_file),
            patch.object(config, "PRIORITY_GROUPS", json.loads(json.dumps(GROUPS))),
            patch.object(config, "AUTO_SWAP", True),
            patch.object(config, "AUTO_SWAP_DRY_RUN", False),
            patch.object(monitor, "_choosed_fetch_failing", False),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self._tmp.cleanup)

    def _write_catalog(self, choosed):
        self.catalog_file.write_text(json.dumps(
            {"courses": [{"kch": "KEEP"}], "user": {"xm": "张三"}, "choosed": choosed},
            ensure_ascii=False,
        ), "utf-8")


class UnscheduledTests(unittest.TestCase):
    def test_blank_and_placeholders_are_unscheduled(self):
        for value in (None, "", "  ", "--", "待定", "不排教室"):
            self.assertTrue(timetable.is_unscheduled(value), value)

    def test_unparseable_text_is_not_unscheduled(self):
        self.assertFalse(timetable.is_unscheduled("星期八"))
        self.assertFalse(timetable.is_unscheduled(MON_12))


class HeldAndConflictTests(_TempFiles):
    def test_held_is_highest_priority_chosen_in_group(self):
        held = monitor._held_from_choosed({"en-low", "en-held", "other"})
        self.assertEqual(held, {"英语": "en-held"})

    def test_conflict_ignores_own_group_and_unscheduled_courses(self):
        current = {"en-a": row("en-a", MON_12)}
        choosed = {
            "en-held": row("en-held", MON_12),   # 本组持有,即将换掉
            "tbd": row("tbd", "待定"),             # 不排课
        }
        self.assertEqual(
            monitor._conflict_with_choosed(current, "英语", "en-a", choosed),
            (None, None, False),
        )

    def test_conflict_with_chosen_course_outside_any_group(self):
        current = {"en-a": row("en-a", MON_12)}
        choosed = {"free": row("free", MON_23)}
        other, detail, unknown = monitor._conflict_with_choosed(current, "英语", "en-a", choosed)
        self.assertEqual(other["jxb_id"], "free")
        self.assertIn("第2节", detail)
        self.assertFalse(unknown)

    def test_unparseable_chosen_schedule_is_unknown(self):
        current = {"en-a": row("en-a", MON_12)}
        _, _, unknown = monitor._conflict_with_choosed(
            current, "英语", "en-a", {"odd": row("odd", "星期八")}
        )
        self.assertTrue(unknown)

    def test_conflict_marks_cover_watched_targets_by_group(self):
        current = {k: row(k, s) for k, s in
                   (("en-a", MON_12), ("en-b", WED_12), ("ph-a", "星期八"))}
        choosed = {"en-held": row("en-held", TUE_12), "ph-held": row("ph-held", MON_23)}
        marks = monitor.conflict_marks(current, {"en-a", "en-b", "ph-a"}, choosed)
        self.assertEqual(marks["英语"], {"en-a": {"status": "conflict", "with": "ph-held",
                                                  "detail": "周一 第2节 (第1周)"}})
        self.assertEqual(marks["物理"], {"ph-a": {"status": "unknown"}})


class AutoSwapTests(_TempFiles):
    def test_group_without_chosen_selects_highest_non_conflicting_directly(self):
        current = {k: row(k, s) for k, s in
                   (("en-a", MON_12), ("en-b", WED_12), ("en-low", TUE_12))}
        choosed = {"free": row("free", MON_23)}
        with patch.object(monitor.swap_mod, "select_course", return_value=(True, "{'flag': '1'}")) as sel, \
             patch.object(monitor.swap_mod, "drop_then_select") as dts:
            results = monitor.maybe_auto_swap(
                None, [spot("en-low"), spot("en-a"), spot("en-b")], current, choosed,
            )
        dts.assert_not_called()
        sel.assert_called_once_with(None, "en-b", is_pe=False, dry_run=False)
        kinds = [(r["kind"], r.get("target")) for r in results]
        self.assertEqual(kinds, [("conflict_skipped", "en-a"), ("swap_result", "en-b")])
        self.assertEqual(results[0]["conflict_course"], "free free-班")
        self.assertIsNone(results[1]["drop"])
        self.assertIn("en-b", choosed)
        self.assertEqual(json.loads(self.swap_state_file.read_text("utf-8"))["completed"], ["en-b"])

    def test_held_group_drops_actual_held_and_never_downgrades(self):
        current = {k: row(k, s) for k, s in
                   (("en-a", MON_12), ("en-b", WED_12), ("en-low", TUE_12))}
        # 用户手动选了 en-held(方案末项是 en-low),实际持有应为 en-held
        choosed = {"en-held": row("en-held", TUE_12), "ph-held": row("ph-held", MON_23)}
        with patch.object(monitor.swap_mod, "drop_then_select", return_value=(True, "ok")) as dts, \
             patch.object(monitor.swap_mod, "select_course") as sel:
            results = monitor.maybe_auto_swap(
                None, [spot("en-low"), spot("en-a"), spot("en-b")], current, choosed,
            )
        sel.assert_not_called()
        dts.assert_called_once_with(None, drop_jxb_id="en-held", select_jxb_id="en-b",
                                    is_pe=False, dry_run=False)
        self.assertNotIn("en-low", [r.get("target") for r in results])
        self.assertEqual(set(choosed), {"en-b", "ph-held"})

    def test_fatal_removes_dropped_class_from_choosed(self):
        current = {"en-a": row("en-a", WED_12)}
        choosed = {"en-held": row("en-held", TUE_12)}
        with patch.object(monitor.swap_mod, "drop_then_select", return_value=(False, "FATAL_LOST")):
            monitor.maybe_auto_swap(None, [spot("en-a")], current, choosed)
        self.assertEqual(choosed, {})
        state = json.loads(self.swap_state_file.read_text("utf-8"))
        self.assertEqual(state["fatal_groups"], ["英语"])

    def test_without_choosed_record_falls_back_to_config_held(self):
        current = {"en-a": row("en-a", WED_12), "ph-held": row("ph-held", MON_12)}
        with patch.object(monitor.swap_mod, "drop_then_select", return_value=(True, "ok")) as dts:
            monitor.maybe_auto_swap(None, [spot("en-a")], current, None)
        dts.assert_called_once_with(None, drop_jxb_id="en-low", select_jxb_id="en-a",
                                    is_pe=False, dry_run=False)


class ResolveChoosedTests(_TempFiles):
    def test_live_result_is_saved_and_changes_are_reported(self):
        self._write_catalog([row("en-low", TUE_12)])
        with patch.object(monitor, "fetch_choosed", return_value=[row("en-held", TUE_12)]):
            choosed, notes = monitor.resolve_choosed(None)
        self.assertEqual(set(choosed), {"en-held"})
        self.assertEqual(notes[0]["kind"], "choosed_changed")
        self.assertEqual(notes[0]["added"], ["en-held en-held-班"])
        self.assertEqual(notes[0]["removed"], ["en-low en-low-班"])
        catalog = json.loads(self.catalog_file.read_text("utf-8"))
        self.assertEqual([c["jxb_id"] for c in catalog["choosed"]], ["en-held"])
        self.assertEqual(catalog["courses"], [{"kch": "KEEP"}])
        self.assertEqual(catalog["user"], {"xm": "张三"})

    def test_failure_uses_saved_record_and_alerts_once_until_recovery(self):
        self._write_catalog([row("en-held", TUE_12)])
        with patch.object(monitor, "fetch_choosed", return_value=None):
            first, first_notes = monitor.resolve_choosed(None)
            second, second_notes = monitor.resolve_choosed(None)
        self.assertEqual(set(first), {"en-held"})
        self.assertEqual(first_notes, [{"kind": "choosed_fetch_failed", "fallback": "saved", "count": 1}])
        self.assertEqual(set(second), {"en-held"})
        self.assertEqual(second_notes, [])
        with patch.object(monitor, "fetch_choosed", return_value=[row("en-held", TUE_12)]):
            _, recovered = monitor.resolve_choosed(None)
        self.assertEqual([n["kind"] for n in recovered], ["choosed_fetch_recovered"])

    def test_failure_without_record_returns_none(self):
        with patch.object(monitor, "fetch_choosed", return_value=None):
            choosed, notes = monitor.resolve_choosed(None)
        self.assertIsNone(choosed)
        self.assertEqual(notes[0]["fallback"], "config")
        self.assertFalse(self.catalog_file.exists())

    def test_corrupt_catalog_is_not_overwritten(self):
        self.catalog_file.write_text("{broken", "utf-8")
        monitor.save_choosed({"en-held": row("en-held", TUE_12)})
        self.assertEqual(self.catalog_file.read_text("utf-8"), "{broken")

    def test_run_once_saves_post_swap_record_for_later_failures(self):
        self._write_catalog([row("en-held", TUE_12)])
        current = [row("en-a", WED_12, sel="1", cap="30")]
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(config, "STATE_FILE", Path(temp) / "state.json"), \
             patch.object(config, "LOG_FILE", Path(temp) / "changes.log"), \
             patch.object(monitor, "fetch_courses", return_value=(current, set())), \
             patch.object(monitor, "fetch_choosed", return_value=None), \
             patch.object(monitor.swap_mod, "drop_then_select", return_value=(True, "ok")), \
             patch.object(monitor.notifier, "send") as send:
            monitor.run_once(None, {})
        catalog = json.loads(self.catalog_file.read_text("utf-8"))
        self.assertEqual([c["jxb_id"] for c in catalog["choosed"]], ["en-a"])
        kinds = [c["kind"] for c in send.call_args.args[0]]
        self.assertEqual(kinds, ["choosed_fetch_failed", "swap_result"])

class PartialFetchTests(_TempFiles):
    """接口 200 返回空列表时，残缺快照不能覆盖 state.json，也不能误报教学班被删除。"""

    def test_empty_course_query_keeps_last_round_classes(self):
        self._write_catalog([row("en-held", TUE_12)])
        previous = {
            "en-a": {**row("en-a", WED_12), "kch": "EN01"},
            "ph-a": {**row("ph-a", MON_12), "kch": "PH01"},
        }
        fetched = [{**row("en-a", WED_12), "kch": "EN01"}]
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(config, "STATE_FILE", Path(temp) / "state.json"), \
             patch.object(config, "LOG_FILE", Path(temp) / "changes.log"), \
             patch.object(config, "AUTO_SWAP", False), \
             patch.object(monitor, "fetch_courses", return_value=(fetched, {"PH01"})), \
             patch.object(monitor, "fetch_choosed",
                          return_value=[row("en-held", TUE_12)]), \
             patch.object(monitor.notifier, "send") as send:
            current = monitor.run_once(None, previous)
            saved = json.loads((Path(temp) / "state.json").read_text("utf-8"))
        # PH01 本轮一个班都没返回 → 沿用上一轮，不写成“已删除”
        self.assertEqual(sorted(current), ["en-a", "ph-a"])
        self.assertEqual(sorted(saved), ["en-a", "ph-a"])
        send.assert_not_called()

    def test_single_class_disappearing_is_still_a_real_change(self):
        self._write_catalog([row("en-held", TUE_12)])
        previous = {
            "en-a": {**row("en-a", WED_12), "kch": "EN01"},
            "en-b": {**row("en-b", WED_12), "kch": "EN01"},
        }
        fetched = [{**row("en-a", WED_12), "kch": "EN01"}]
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(config, "STATE_FILE", Path(temp) / "state.json"), \
             patch.object(config, "LOG_FILE", Path(temp) / "changes.log"), \
             patch.object(config, "AUTO_SWAP", False), \
             patch.object(monitor, "fetch_courses", return_value=(fetched, set())), \
             patch.object(monitor, "fetch_choosed",
                          return_value=[row("en-held", TUE_12)]), \
             patch.object(monitor.notifier, "send") as send:
            current = monitor.run_once(None, previous)
        self.assertEqual(sorted(current), ["en-a"])
        self.assertEqual([c["kind"] for c in send.call_args.args[0]], ["removed"])


if __name__ == "__main__":
    unittest.main()
