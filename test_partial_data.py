"""残缺数据不覆盖好数据的离线单测(不联网):bootstrap 部分来源失败 + zzxk 请求失败语义。"""
import json
import unittest
from unittest.mock import MagicMock, patch

import bootstrap
import config
import zzxk
from test_terms import _IsolatedConfig

SITE = {"xkxnm": "2026", "xkxqm": "3", "label": "2026-2027 第1学期（秋）",
        "zzxk_open": True, "tjxkbkk_open": True}

PREVIOUS = {
    "fetched_at": "2026-09-14T14:15:35",
    "user": {"xm": "张三", "xh": "525010910066", "bjmc": "船建2511",
             "zymc": "船舶与海洋工程", "zyh_id": "ZY", "njdm_id": "2025"},
    "courses": [
        {"kch": "CS0501", "endpoint": "zzxk", "kcmc": "数据结构",
         "classes": [{"jxb_id": "cs-1"}]},
        {"kch": "PE003", "endpoint": "pe", "kcmc": "体育",
         "classes": [{"jxb_id": "pe-1"}]},
    ],
    "choosed": [{"jxb_id": "held-1", "kcmc": "已选课"}],
}

FRESH_ZZXK = [{"kch": "CS0502", "endpoint": "zzxk", "kcmc": "计算机科学导论",
               "classes": [{"jxb_id": "cs-2"}]}]


def _boom(*_args, **_kwargs):
    raise RuntimeError("接口抖动")


class PartialCatalogTests(_IsolatedConfig):
    def setUp(self):
        super().setUp()
        self.load()
        config.CATALOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        config.CATALOG_FILE.write_text(json.dumps(PREVIOUS, ensure_ascii=False), "utf-8")

    def run_bootstrap(self, *, zzxk_catalog, pe_catalog, choosed, xsxx):
        self.relogin = MagicMock()
        with patch.object(bootstrap, "detect_site_term", return_value=(SITE, {}, {})), \
             patch.object(bootstrap, "ensure_session", self.relogin), \
             patch.object(bootstrap, "fetch_xsxx", xsxx), \
             patch.object(bootstrap, "fetch_zzxk_catalog", zzxk_catalog), \
             patch.object(bootstrap, "fetch_pe_catalog", pe_catalog), \
             patch.object(bootstrap, "fetch_choosed", choosed), \
             patch.object(zzxk, "fetch_choosed", choosed):
            return bootstrap.run(MagicMock())

    def saved_catalog(self):
        return json.loads(config.CATALOG_FILE.read_text("utf-8"))

    def test_failed_sources_reuse_previous_data_instead_of_wiping_it(self):
        # zzxk 拿到新数据，体育课/已选/个人信息三个接口都挂了。
        catalog = self.run_bootstrap(
            zzxk_catalog=MagicMock(return_value=FRESH_ZZXK),
            pe_catalog=_boom,
            choosed=_boom,
            xsxx=_boom,
        )
        saved = self.saved_catalog()
        self.assertEqual(saved, catalog)
        self.assertEqual([c["kch"] for c in saved["courses"]], ["CS0502", "PE003"])
        self.assertEqual([c["jxb_id"] for c in saved["choosed"]], ["held-1"])
        self.assertEqual(saved["user"]["xm"], "张三")
        self.assertEqual(saved["stale"], ["choosed", "pe", "user"])

    def test_empty_response_counts_as_no_data(self):
        # 接口 200 但返回空列表，同样不能把已抓好的目录清成空。
        self.run_bootstrap(
            zzxk_catalog=MagicMock(return_value=[]),
            pe_catalog=MagicMock(return_value=[]),
            choosed=MagicMock(return_value=[{"jxb_id": "held-2", "kcmc": "新已选"}]),
            xsxx=MagicMock(return_value={"XM": "张三", "XH": "525010910066"}),
        )
        saved = self.saved_catalog()
        self.assertEqual([c["kch"] for c in saved["courses"]], ["CS0501", "PE003"])
        self.assertEqual([c["jxb_id"] for c in saved["choosed"]], ["held-2"])
        self.assertEqual(saved["stale"], ["pe", "user", "zzxk"])
        # 个人课表只回了姓名学号，其余字段沿用旧值而不是写成 null
        self.assertEqual(saved["user"]["bjmc"], "船建2511")

    def test_whole_round_without_fresh_data_keeps_the_file_untouched(self):
        with self.assertRaises(bootstrap.BootstrapFailure) as failure:
            self.run_bootstrap(
                zzxk_catalog=_boom, pe_catalog=_boom, choosed=_boom, xsxx=_boom,
            )
        self.assertEqual((failure.exception.reason, failure.exception.exit_code),
                         ("empty", 4))
        self.assertEqual(self.saved_catalog(), PREVIOUS)

    def test_session_kicked_midway_reports_it_and_writes_nothing(self):
        def kicked(*_a, **_k):
            raise zzxk.SessionExpired("被顶掉: status=901")

        with self.assertRaises(bootstrap.BootstrapFailure) as failure:
            self.run_bootstrap(zzxk_catalog=kicked, pe_catalog=kicked,
                               choosed=kicked, xsxx=_boom)
        self.assertEqual((failure.exception.reason, failure.exception.exit_code),
                         ("session", 5))
        self.assertIn("同一账号", str(failure.exception))
        self.assertEqual(self.saved_catalog(), PREVIOUS)
        # 掉线后会重新取一次共享会话再整轮重来,两次都掉线才报错
        self.relogin.assert_called_once()

    def test_skip_catalog_keeps_the_existing_course_list(self):
        with patch.object(bootstrap, "detect_site_term", return_value=(SITE, {}, {})), \
             patch.object(bootstrap, "fetch_xsxx", MagicMock(return_value={})), \
             patch.object(bootstrap, "fetch_choosed",
                          MagicMock(return_value=[{"jxb_id": "held-2"}])), \
             patch.object(zzxk, "fetch_choosed", MagicMock(return_value=[])):
            bootstrap.run(MagicMock(), skip_catalog=True)
        saved = self.saved_catalog()
        self.assertEqual([c["kch"] for c in saved["courses"]], ["CS0501", "PE003"])
        self.assertEqual([c["jxb_id"] for c in saved["choosed"]], ["held-2"])


def _response(status, ct, text="[]"):
    r = MagicMock()
    r.status_code = status
    r.headers = {"content-type": ct}
    r.text = text
    r.json.return_value = json.loads(text) if ct.startswith("application/json") else None
    return r


class ZzxkFailureTests(unittest.TestCase):
    """请求失败(302/空响应)必须和"服务端合法地回了空结果"区分开。"""

    def setUp(self):
        patcher = patch.object(zzxk.time, "sleep")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_post_json_retries_once_then_succeeds(self):
        session = MagicMock()
        session.post.side_effect = [_response(200, "text/html", ""),
                                    _response(200, "application/json", '{"ok": 1}')]
        self.assertEqual(
            zzxk._post_json(session, "u", {}, what="PartDisplay"), {"ok": 1})
        self.assertEqual(session.post.call_count, 2)

    def test_post_json_gives_up_with_none_not_empty(self):
        session = MagicMock()
        session.post.return_value = _response(500, "text/html", "")
        self.assertIsNone(zzxk._post_json(session, "u", {}, what="JxbWithKch"))
        self.assertEqual(session.post.call_count, 2)

    def test_session_status_raises_immediately_without_retrying(self):
        # 901 = 正方 ajax 接口在会话被顶掉后的返回(2026-09-16 联网实测,响应体为空)
        for status in (302, 401, 403, 901):
            session = MagicMock()
            session.post.return_value = _response(status, "", "")
            with self.subTest(status=status), \
                 self.assertRaises(zzxk.SessionExpired):
                zzxk._post_json(session, "u", {}, what="PartDisplay")
            self.assertEqual(session.post.call_count, 1)

    def test_failed_page_is_not_treated_as_end_of_category(self):
        pages = [[{"jxb_id": "a", "kch_id": "K", "kch": "K1"}], None]
        with patch.object(zzxk, "fetch_part_display", side_effect=pages),              self.assertLogs("zzxk", level="WARNING") as logs:
            rows = zzxk.sweep_category(MagicMock(), {"kklxdm": "01"}, jspage=1)
        self.assertEqual([r["jxb_id"] for r in rows], ["a"])
        self.assertIn("目录可能不完整", "".join(logs.output))

    def test_empty_page_still_ends_the_category(self):
        with patch.object(zzxk, "fetch_part_display",
                          side_effect=[[{"jxb_id": "a"}], []]) as page:
            rows = zzxk.sweep_category(MagicMock(), {"kklxdm": "01"}, jspage=1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(page.call_count, 2)

    def test_hitting_the_window_cap_is_reported_as_truncation(self):
        with patch.object(zzxk, "fetch_part_display",
                          return_value=[{"jxb_id": "x"}]), \
             self.assertLogs("zzxk", level="WARNING") as logs:
            zzxk.sweep_category(MagicMock(), {"kklxdm": "69"},
                                max_windows=2, jspage=3)
        self.assertIn("目录被截断", "".join(logs.output))

    def test_default_window_leaves_room_for_the_largest_real_category(self):
        # 2026-09-16 实测:交叉课程(69)有 286 门课;旧默认 15*10=150 会砍掉一半
        self.assertGreaterEqual(zzxk._MAX_WINDOWS * zzxk._WINDOW_COURSES, 1000)

    def test_failed_choosed_query_raises_instead_of_returning_empty(self):
        session = MagicMock()
        session.post.return_value = _response(500, "text/html", "")
        with self.assertRaises(zzxk.SessionExpired):
            zzxk.fetch_choosed(session, source={"xkxnm": "2026"})


if __name__ == "__main__":
    unittest.main()
