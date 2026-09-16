"""选课社区评分按老师匹配的离线单测(不联网)。

背景:评分在 course.sjtu.plus 上是**按老师**分开的,同一课程代码有几十上百条。
旧实现只取第一页、匹配不上就取第一条(列表按分数降序),于是显示成"课程对、老师不对"。
"""
import json
import unittest
from unittest.mock import MagicMock, patch

import bootstrap
import course_plus
import gui_backend


def item(course_id, teacher, tid, semester, count, score, code="CS0501"):
    return {
        "id": course_id, "code": code, "name": "数据结构",
        "main_teacher": {"id": course_id, "code": tid, "name": teacher},
        "last_semester": semester,
        "rating": {"count": count, "avg": score, "score": score},
    }


PAGE_1 = [
    item(1, "陈帅", "20471", "2026-2027-1", 25, 3.5),
    item(2, "郭晓莉", "10498", "2026-2027-1", 17, 4.7),
    item(3, "郭晓莉", "10498", "2020-2021-1", 2, 2.0),   # 同一老师的旧学期
    {"id": 9, "code": "CS9999", "name": "别的课",          # q 模糊命中的噪声
     "main_teacher": {"code": "1", "name": "张三"},
     "last_semester": "2026-2027-1", "rating": {"count": 1, "score": 5}},
]
PAGE_2 = [item(4, "刘海涛", "09325", "2026-2027-1", 0, 0)]


def _session(pages):
    session = MagicMock()

    def get(url, params=None, timeout=None):
        page = (params or {}).get("page", 1)
        rows = pages[page - 1] if page - 1 < len(pages) else []
        response = MagicMock()
        response.json.return_value = {"items": rows, "total": sum(len(p) for p in pages)}
        return response

    session.get.side_effect = get
    return session


class FetchRatingsTests(unittest.TestCase):
    def test_pages_through_all_candidates_and_keeps_the_newest_per_teacher(self):
        # page_size=4 → 第一页满,必须继续翻第二页才能拿到刘海涛
        table = course_plus.fetch_course_ratings(
            _session([PAGE_1, PAGE_2]), "CS0501", page_size=4)
        self.assertEqual(sorted(table["teachers"]), ["09325", "10498", "20471"])
        self.assertEqual(table["teachers"]["10498"]["semester"], "2026-2027-1")
        self.assertEqual(table["teachers"]["10498"]["rating"]["count"], 17)
        self.assertEqual(table["by_name"]["刘海涛"], "09325")

    def test_unrelated_code_from_fuzzy_search_is_dropped(self):
        table = course_plus.fetch_course_ratings(_session([PAGE_1]), "CS0501")
        self.assertNotIn("1", table["teachers"])

    def test_missing_course_returns_none(self):
        self.assertIsNone(course_plus.fetch_course_ratings(_session([[]]), "CS0501"))

    def test_lookup_prefers_the_staff_id_over_the_name(self):
        table = course_plus.fetch_course_ratings(
            _session([PAGE_1, PAGE_2]), "CS0501", page_size=4)
        by_id = course_plus.lookup_teacher(table, teacher_id="09325", teacher_name="陈帅")
        self.assertEqual(by_id["teacher"], "刘海涛")
        by_name = course_plus.lookup_teacher(table, teacher_name="陈帅")
        self.assertEqual(by_name["teacher_id"], "20471")
        self.assertIsNone(course_plus.lookup_teacher(table, teacher_name="查无此人"))

    def test_named_teacher_without_a_record_yields_nothing_rather_than_someone_else(self):
        with patch.object(course_plus, "search_course_by_code",
                          return_value=PAGE_1 + PAGE_2):
            self.assertIsNone(course_plus.get_rating_by_code(
                MagicMock(), "CS0501", teacher_name="查无此人"))
            hit = course_plus.get_rating_by_code(
                MagicMock(), "CS0501", teacher_id="10498")
        self.assertEqual(hit["teacher"], "郭晓莉")


RECORD = {
    "code": "CS0501", "name": "数据结构", "updated_at": "2026-09-16T14:00:00",
    "teachers": {
        "10498": {"teacher": "郭晓莉", "teacher_id": "10498", "semester": "2026-2027-1",
                  "rating": {"count": 17, "score": 4.7}},
        "20471": {"teacher": "陈帅", "teacher_id": "20471", "semester": "2026-2027-1",
                  "rating": {"count": 0, "score": 0}},
    },
    "by_name": {"郭晓莉": "10498", "陈帅": "20471"},
    "rating": {"count": 17, "score": 4.7, "teacher_count": 2},
    "teacher": None, "semester": "2026-2027-1",
}


class ClassRatingTests(unittest.TestCase):
    def _row(self, jsxx):
        return {"kch": "CS0501", "jsxx": jsxx, "rating": RECORD}

    def test_class_uses_its_own_teacher(self):
        rating = gui_backend.normalized_rating(self._row("10498/郭晓莉/副研究员"))
        self.assertEqual((rating["status"], rating["teacher"], rating["count"]),
                         ("rated", "郭晓莉", 17))

    def test_second_teacher_of_a_class_still_matches(self):
        rating = gui_backend.normalized_rating(
            self._row("99999/张三/教授;20471/陈帅/讲师"))
        self.assertEqual(rating["teacher"], "陈帅")
        self.assertEqual(rating["status"], "empty")   # 收录了但 0 条评价

    def test_name_only_jsxx_falls_back_to_matching_by_name(self):
        rating = gui_backend.normalized_rating(self._row("郭晓莉"))
        self.assertEqual((rating["status"], rating["teacher"]), ("rated", "郭晓莉"))

    def test_unknown_teacher_is_not_given_somebody_elses_score(self):
        row = self._row("77777/李四/教授")
        rating = gui_backend.normalized_rating(row)
        self.assertEqual(rating["status"], "teacher_unrated")
        self.assertIsNone(rating["teacher"])
        self.assertIn("李四", rating["message"])
        self.assertEqual(gui_backend.rating_text(row), "本班老师无评价")

    def test_legacy_course_level_cache_still_renders(self):
        legacy = {"code": "CS0501", "teacher": "郭晓莉", "semester": "2025-2026-1",
                  "rating": {"count": 5, "score": 4.0}, "updated_at": "旧"}
        rating = gui_backend.normalized_rating({"kch": "CS0501", "jsxx": "1/王五/教授",
                                                "rating": legacy})
        self.assertEqual((rating["status"], rating["score"]), ("rated", 4.0))
        self.assertIn("重新获取", rating["message"])

    def test_aggregate_is_weighted_by_review_count(self):
        agg = bootstrap._aggregate_rating([
            {"rating": {"count": 10, "score": 4.0}},
            {"rating": {"count": 30, "score": 3.0}},
            {"rating": {"count": 0, "score": 0}},
        ])
        self.assertEqual((agg["count"], agg["score"], agg["teacher_count"]),
                         (40, 3.25, 3))


if __name__ == "__main__":
    unittest.main()
