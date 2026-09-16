"""按学期保存配置、学期切换与教务网站学期检测的离线单测(不联网)。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import bootstrap
import config
import gui_backend

_GLOBALS = (
    "XKXNM", "XKXQM", "ACTIVE_TERM", "TERM_DIR", "QUERY_OVERRIDES", "KCH_QUERIES",
    "PRIORITY_GROUPS", "AUTO_SWAP", "AUTO_SWAP_DRY_RUN", "SITE_TERM", "EMAIL_ENABLED",
    "STATE_FILE", "SWAP_STATE_FILE", "CATALOG_FILE", "ZZXK_CAPACITY_FILE", "SEAT_DETAILS_FILE",
)


class _IsolatedConfig(unittest.TestCase):
    """把 config 的数据目录与模块级设置换成临时副本,结束后还原。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        saved = {name: getattr(config, name) for name in _GLOBALS}

        def restore():
            for name, value in saved.items():
                setattr(config, name, value)

        self.addCleanup(restore)
        for p in (
            patch.object(config, "DATA_DIR", self.root),
            patch.object(config, "TERMS_DIR", self.root / "terms"),
            patch.object(config, "USER_SETTINGS_FILE", self.root / "user_settings.json"),
            patch.object(config, "_LEGACY_PRIORITY_FILE", self.root / "priority_groups.json"),
            patch.object(config, "USER_SETTINGS", config.default_settings()),
        ):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self._tmp.cleanup)

    def write_settings(self, data):
        (self.root / "user_settings.json").write_text(json.dumps(data, ensure_ascii=False), "utf-8")

    def load(self):
        config.USER_SETTINGS = config.load_user_settings()
        config._apply_settings(config.USER_SETTINGS)


class TermSettingsTests(_IsolatedConfig):
    def test_legacy_top_level_plan_moves_into_active_term(self):
        groups = {"物理": {"is_pe": False, "priority": ["a", "b"]}}
        self.write_settings({"term": {"xkxnm": "2026", "xkxqm": "3"},
                             "priority_groups": groups, "courses": {"PHY": {"endpoint": "display"}}})
        self.load()
        self.assertEqual(config.ACTIVE_TERM, "2026-3")
        self.assertEqual(config.PRIORITY_GROUPS, groups)
        self.assertEqual(config.USER_SETTINGS["terms"]["2026-3"]["priority_groups"], groups)
        self.assertNotIn("priority_groups", config.USER_SETTINGS)

    def test_existing_term_section_wins_over_legacy_keys(self):
        self.write_settings({
            "term": {"xkxnm": "2026", "xkxqm": "3"},
            "priority_groups": {"旧": {"priority": ["x"]}},
            "terms": {"2026-3": {"priority_groups": {}}},
        })
        self.load()
        # 显式空分区不被旧值或默认值"复活"
        self.assertEqual(config.PRIORITY_GROUPS, {})

    def test_switching_terms_keeps_plans_and_files_separate(self):
        self.write_settings({"term": {"xkxnm": "2026", "xkxqm": "3"},
                             "terms": {"2026-3": {"priority_groups": {"秋": {"priority": ["a"]}}}}})
        self.load()
        self.assertEqual(config.set_active_term("2026", "12"), "2026-12")
        self.assertEqual(config.PRIORITY_GROUPS, {})
        self.assertEqual(config.CATALOG_FILE, self.root / "terms" / "2026-12" / "catalog.json")
        config.update_user_settings(priority_groups={"春": {"priority": ["b"]}})
        config.set_active_term("2026", "3")
        self.assertEqual(list(config.PRIORITY_GROUPS), ["秋"])
        self.assertEqual(config.SWAP_STATE_FILE, self.root / "terms" / "2026-3" / "swap_state.json")
        saved = json.loads((self.root / "user_settings.json").read_text("utf-8"))
        self.assertEqual(saved["term"], {"xkxnm": "2026", "xkxqm": "3"})
        self.assertEqual(list(saved["terms"]["2026-12"]["priority_groups"]), ["春"])
        self.assertEqual(config.known_terms(), ["2026-12", "2026-3"])

    def test_invalid_term_is_rejected(self):
        self.load()
        for xkxnm, xkxqm in (("26", "3"), ("2026", "秋"), ("", "")):
            with self.subTest(xkxnm=xkxnm, xkxqm=xkxqm), self.assertRaises(ValueError):
                config.set_active_term(xkxnm, xkxqm)

    def test_legacy_state_files_are_copied_once_and_kept(self):
        (self.root / "catalog.json").write_text('{"courses": []}', "utf-8")
        (self.root / "ratings.json").write_text("{}", "utf-8")
        settings = config.default_settings()
        config._migrate_legacy_term_files(settings)
        copied = self.root / "terms" / "2026-3" / "catalog.json"
        self.assertEqual(copied.read_text("utf-8"), '{"courses": []}')
        self.assertTrue((self.root / "catalog.json").exists())
        self.assertFalse((self.root / "terms" / "2026-3" / "ratings.json").exists())
        (self.root / "catalog.json").write_text("newer", "utf-8")
        config._migrate_legacy_term_files(settings)
        self.assertEqual(copied.read_text("utf-8"), '{"courses": []}')

    def test_term_labels(self):
        site = {"xkxnm": "2026", "xkxqm": "3", "xkxnmc": "2026-2027", "xkxqmc": "1"}
        self.assertEqual(config.term_label("2026", "3", site), "2026-2027 第1学期（秋）")
        self.assertEqual(config.term_label("2026", "12"), "2026-2027 第2学期（春）")
        self.assertEqual(config.term_label("2025", "16"), "2025-2026 第3学期（夏）")
        self.assertEqual(config.term_label("2026", "99"), "2026-2027 学期代码99")


def _response(status, text):
    r = MagicMock()
    r.status_code = status
    r.text = text
    return r


OPEN_PAGE = ('<input type="hidden" id="xkxnm" value="2026"/>'
             '<input type="hidden" id="xkxqm" value="3"/>'
             '<input type="hidden" id="xkkz_id" value="52C4"/>')


class SiteTermTests(_IsolatedConfig):
    def test_detects_term_from_open_modules(self):
        self.load()
        session = MagicMock()
        session.get.return_value = _response(200, OPEN_PAGE)
        zzxk_hidden = {"xkxnm": "2026", "xkxqm": "3", "xkxnmc": "2026-2027", "xkxqmc": "1"}
        with patch.object(bootstrap.zzxk, "fetch_index", return_value=(zzxk_hidden, [{"kklxdm": "01"}])):
            site, _, page_hidden = bootstrap.detect_site_term(session)
        self.assertEqual((site["xkxnm"], site["xkxqm"]), ("2026", "3"))
        self.assertTrue(site["zzxk_open"] and site["tjxkbkk_open"])
        self.assertEqual(site["label"], "2026-2027 第1学期（秋）")
        self.assertEqual(page_hidden["xkkz_id"], "52C4")

    def _closed_site(self, logged_in: bool):
        session = MagicMock()
        session.get.return_value = _response(302, "")
        with patch.object(bootstrap.zzxk, "fetch_index",
                          side_effect=bootstrap.zzxk.SessionExpired("未开放")), \
             patch.object(bootstrap, "is_logged_in", return_value=logged_in):
            site, _, _ = bootstrap.detect_site_term(session)
        return site

    def test_both_modules_closed_yields_no_term(self):
        self.load()
        site = self._closed_site(logged_in=True)
        self.assertNotIn("xkxnm", site)
        self.assertFalse(site["zzxk_open"] or site["tjxkbkk_open"])
        self.assertNotIn("session_error", site)

    def test_lost_session_is_not_reported_as_off_season(self):
        # 掉登录时两个模块首页都被重定向,形态和"非选课期间"一样,必须区分开
        self.load()
        site = self._closed_site(logged_in=False)
        self.assertTrue(site["session_error"])
        with self.assertRaises(bootstrap.BootstrapFailure) as failure:
            bootstrap.check_site_term(site)
        self.assertEqual((failure.exception.reason, failure.exception.exit_code),
                         ("session", 5))
        self.assertIn("登录会话已失效", str(failure.exception))

    def test_check_site_term_reasons(self):
        self.load()
        with self.assertRaises(bootstrap.BootstrapFailure) as closed:
            bootstrap.check_site_term({"zzxk_open": False, "tjxkbkk_open": False})
        self.assertEqual((closed.exception.reason, closed.exception.exit_code), ("closed", 3))

        summer = {"xkxnm": "2025", "xkxqm": "16", "label": "2025-2026 第3学期（夏）"}
        with self.assertRaises(bootstrap.BootstrapFailure) as mismatch:
            bootstrap.check_site_term(summer)
        self.assertEqual(mismatch.exception.reason, "term_mismatch")
        self.assertIn("2025-2026 第3学期（夏）", str(mismatch.exception))
        self.assertEqual(config.ACTIVE_TERM, "2026-3")

        bootstrap.check_site_term({"xkxnm": "2026", "xkxqm": "3"})
        bootstrap.check_site_term(summer, adopt_site_term=True)
        self.assertEqual(config.ACTIVE_TERM, "2025-16")

    def test_run_stops_before_fetching_when_term_mismatches(self):
        self.load()
        site = {"xkxnm": "2025", "xkxqm": "16", "label": "夏", "zzxk_open": True}
        with patch.object(bootstrap, "detect_site_term", return_value=(site, {}, {})), \
             patch.object(bootstrap, "fetch_zzxk_catalog") as catalog, \
             self.assertRaises(bootstrap.BootstrapFailure):
            bootstrap.run(MagicMock())
        catalog.assert_not_called()
        self.assertEqual(config.SITE_TERM["xkxnm"], "2025")
        self.assertFalse(config.CATALOG_FILE.exists())


class GuiTermTests(_IsolatedConfig):
    def test_switch_term_and_options(self):
        self.load()
        config.record_site_term({"xkxnm": "2026", "xkxqm": "3", "xkxnmc": "2026-2027",
                                 "xkxqmc": "1", "zzxk_open": True, "tjxkbkk_open": True})
        self.assertEqual(gui_backend.switch_term({"xkxnm": "2026", "xkxqm": "12"}),
                         {"ok": True, "active_term": "2026-12"})
        options = {item["key"]: item for item in gui_backend.term_options()}
        self.assertTrue(options["2026-12"]["active"])
        self.assertTrue(options["2026-3"]["is_site_term"])
        self.assertEqual(options["2026-3"]["label"], "2026-2027 第1学期（秋）")
        info = gui_backend.site_term_info()
        self.assertEqual(info["key"], "2026-3")
        self.assertFalse(info["matches_active"])


if __name__ == "__main__":
    unittest.main()
