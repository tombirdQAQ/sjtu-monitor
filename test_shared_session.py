"""共享登录会话的离线单测(不联网):多进程只登录一次,不互相顶掉。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

import config
import login as login_mod
import session_store


class SharedSessionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        p = patch.object(config, "DATA_DIR", Path(self._tmp.name))
        p.start()
        self.addCleanup(p.stop)

    def _alive(self, ok=True):
        """把"会话是否仍有效"的探测打桩掉(它会真的发请求)。"""
        p = patch.object(login_mod, "is_logged_in", return_value=ok)
        p.start()
        self.addCleanup(p.stop)

    def _session(self, **cookies):
        s = requests.Session()
        for name, value in cookies.items():
            s.cookies.set(name, value, domain="i.sjtu.edu.cn", path="/")
        return s

    def test_cookies_round_trip_with_a_new_generation_each_login(self):
        first = session_store.save(self._session(JSESSIONID="aaa"))
        restored = requests.Session()
        self.assertEqual(session_store.load(restored), first)
        self.assertEqual(restored.cookies.get("JSESSIONID"), "aaa")
        second = session_store.save(self._session(JSESSIONID="bbb"))
        self.assertNotEqual(first, second)
        self.assertEqual(session_store.generation(), second)

    def test_missing_or_broken_file_reads_as_no_session(self):
        self.assertIsNone(session_store.generation())
        self.assertIsNone(session_store.load(requests.Session()))
        session_store.session_file().write_text("{broken", "utf-8")
        self.assertIsNone(session_store.load(requests.Session()))

    def test_session_of_another_account_is_ignored(self):
        with patch.object(config, "JACCOUNT_USER", "old-user"):
            session_store.save(self._session(JSESSIONID="old"))
        with patch.object(config, "JACCOUNT_USER", "new-user"):
            self.assertIsNone(session_store.load(requests.Session()))

    def test_second_process_reuses_the_first_login(self):
        self._alive()
        def fake_login(session, **_):
            session.cookies.set("JSESSIONID", "shared", domain="i.sjtu.edu.cn", path="/")

        with patch.object(login_mod, "login", side_effect=fake_login) as spy:
            first = requests.Session()
            login_mod.ensure_session(first)
            second = requests.Session()
            login_mod.ensure_session(second)
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(second.cookies.get("JSESSIONID"), "shared")

    def test_force_reuses_a_session_another_process_just_created(self):
        self._alive()
        # 进程 A 先拿到会话,进程 B 期间重新登录了一次(代次变了)。
        with patch.object(login_mod, "login", side_effect=lambda s, **_: None):
            a = requests.Session()
            login_mod.ensure_session(a)
        session_store.save(self._session(JSESSIONID="from-b"))

        with patch.object(login_mod, "login") as spy:
            login_mod.ensure_session(a, force=True)
        spy.assert_not_called()   # 不能再登一次,否则把 B 顶掉
        self.assertEqual(a.cookies.get("JSESSIONID"), "from-b")

    def test_dead_shared_cookies_trigger_a_real_login(self):
        session_store.save(self._session(JSESSIONID="dead"))
        with patch.object(login_mod, "is_logged_in", return_value=False), \
             patch.object(login_mod, "login") as spy:
            login_mod.ensure_session(requests.Session())
        spy.assert_called_once()

    def test_force_logs_in_when_nobody_else_refreshed_it(self):
        self._alive()
        with patch.object(login_mod, "login", side_effect=lambda s, **_: None):
            a = requests.Session()
            login_mod.ensure_session(a)
            before = session_store.generation()
            with patch.object(login_mod, "login") as spy:
                login_mod.ensure_session(a, force=True)
        spy.assert_called_once()
        self.assertNotEqual(session_store.generation(), before)

    def test_lock_is_reentrant_across_sequential_uses(self):
        for _ in range(2):
            with session_store.lock(timeout=5):
                pass

    def test_lock_failure_does_not_block_login(self):
        with patch.object(session_store, "lock_file",
                          return_value=Path(self._tmp.name) / "nope" / "x" / "s.lock"), \
             patch.object(Path, "mkdir", side_effect=OSError("只读目录")):
            with session_store.lock(timeout=1):
                pass  # 退化为不加锁,不能抛异常


if __name__ == "__main__":
    unittest.main()
