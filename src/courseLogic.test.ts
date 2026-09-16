import { describe, expect, it } from "vitest";
import type { ChosenCourse, CourseRow } from "./api";
import {
  bootstrapFailureNotice,
  conflictWarning,
  groupConflictMarks,
  parseBootstrapResult,
  formatRatingScore,
  parseLogLine,
  scheduleConflict,
  sortCourses,
} from "./courseLogic";

function course(
  jxbId: string,
  title: string,
  score: number | null,
  sksj: string,
): CourseRow {
  return {
    jxb_id: jxbId,
    title,
    class_name: title,
    summary: "",
    detail: "",
    teachers: "",
    schedule: [sksj],
    sksj,
    locations: [],
    search_text: title,
    seat_text: "-",
    availability: "unknown",
    availability_text: "未知",
    chosen: false,
    category: "-",
    rating_text: "",
    rating: {
      status: score === null ? "unknown" : "rated",
      score,
      count: null,
      teacher: null,
      semester: null,
      updated_at: null,
      message: null,
    },
  };
}

function chosen(jxbId: string, title: string, sksj: string): ChosenCourse {
  return { jxb_id: jxbId, title, class_name: title, sksj };
}

describe("course sorting and rating formatting", () => {
  it("formats every numeric score with one decimal place", () => {
    expect(formatRatingScore(9.12345)).toBe("9.1");
    expect(formatRatingScore(8)).toBe("8.0");
  });

  it("sorts filtered rows by name or descending rating", () => {
    const rows = [
      course("2", "大学物理", 8.5, "星期一第1-2节{1-16周}"),
      course("1", "高等数学", 9.2, "星期二第1-2节{1-16周}"),
      course("3", "程序设计", null, "星期三第1-2节{1-16周}"),
    ];
    expect(sortCourses(rows, "name").map((row) => row.jxb_id)).toEqual(["3", "2", "1"]);
    expect(sortCourses(rows, "rating").map((row) => row.jxb_id)).toEqual(["1", "2", "3"]);
  });
});

describe("PySide-compatible schedule conflict checks", () => {
  it("handles week ranges and odd/even weeks", () => {
    expect(
      scheduleConflict(
        "星期一第1-2节{1-16周(单)}",
        "星期一第2-3节{2-16周(双)}",
      ),
    ).toEqual({ conflict: false });
    expect(
      scheduleConflict(
        "星期一第1-2节{1-16周(单)}",
        "星期一第2-3节{1-16周}",
      ),
    ).toMatchObject({ conflict: true, detail: "周一 第2节 (第1周)" });
  });

  it("warns only against chosen courses outside the target group", () => {
    const courses = [
      course("new", "新课程", 9, "星期一第1-2节{1-16周}"),
      course("vague", "时间不明", 8, "星期八"),
    ];
    const choosed: ChosenCourse[] = [
      chosen("held-same-group", "本组持有", "星期一第1-2节{1-16周}"),
      chosen("other", "冲突课程", "星期一第2-3节{1-16周}"),
      chosen("tbd", "不排课课程", "待定"),
    ];
    const warning = conflictWarning(["new", "vague"], ["held-same-group"], courses, choosed);
    expect(warning).toContain("新课程 与已选 冲突课程 - 冲突课程");
    expect(warning).toContain("周一 第2节 (第1周)");
    expect(warning).not.toContain("本组持有");
    expect(warning).toContain("缺少时间数据");
    expect(warning).toContain("时间不明");
    expect(conflictWarning(["new"], [], courses, [chosen("tbd", "不排课课程", "待定")])).toBeNull();
  });
});

describe("groupConflictMarks", () => {
  const courses = [
    course("a", "A", null, "星期二第1-2节{1-16周}"),
    course("b", "B", null, "星期三第1-2节{1-16周}"),
    course("held", "Held", null, "星期二第1-2节{1-16周}"),
    course("low", "Low", null, "星期二第1-2节{1-16周}"),
  ];
  const outside = chosen("x", "外部课", "星期二第2-3节{1-8周}");

  it("marks only candidates above the highest chosen class in the group", () => {
    const marks = groupConflictMarks(
      ["a", "b", "held", "low"],
      courses,
      [chosen("held", "Held", "星期二第1-2节{1-16周}"), chosen("low", "Low", "星期二第1-2节{1-16周}"), outside],
    );
    expect([...marks.keys()]).toEqual(["a"]);
    expect(marks.get("a")).toMatchObject({ status: "conflict", with: "外部课 - 外部课" });
  });

  it("checks the whole group when nothing in it is chosen", () => {
    const marks = groupConflictMarks(["a", "b", "low"], courses, [outside]);
    expect([...marks.keys()].sort()).toEqual(["a", "low"]);
  });

  it("returns no marks without chosen courses outside the group", () => {
    expect(groupConflictMarks(["a", "held"], courses, [chosen("held", "Held", "星期二第1-2节{1-16周}")]).size).toBe(0);
  });
});

describe("parseLogLine", () => {
  it("parses python logging lines with level and logger name", () => {
    const line = parseLogLine("monitor", "2026-07-18 14:02:11,123 WARNING [monitor] 查询失败，将重试");
    expect(line.time).toBe("14:02:11");
    expect(line.level).toBe("warn");
    expect(line.source).toBe("monitor");
    expect(line.message).toBe("查询失败，将重试");
  });

  it("formats change records and maps swap failures to error", () => {
    const record = JSON.stringify({
      kind: "swap_result", ok: false, status: "FULL", kcmc: "大学物理", jxbmc: "PHY1262-03",
    });
    const line = parseLogLine("changes", `2026-07-18T09:00:00 ${record}`);
    expect(line.level).toBe("error");
    expect(line.message).toContain("换课失败");
    expect(line.message).toContain("PHY1262-03 大学物理");
  });

  it("maps spot_open records to warn with readable text", () => {
    const record = JSON.stringify({ kind: "spot_open", kcmc: "线性代数", jxbmc: "MA0301-01", msg: "剩余1" });
    const line = parseLogLine("changes", `2026-07-18T09:00:00 ${record}`);
    expect(line.level).toBe("warn");
    expect(line.message).toContain("有空位");
  });

  it("formats field-change records with chinese labels", () => {
    const record = JSON.stringify({ kind: "changed", kcmc: "高数", jxbmc: "MA01", changes: { yxzrs: [28, 29] } });
    const line = parseLogLine("changes", `2026-07-18T09:00:00 ${record}`);
    expect(line.level).toBe("info");
    expect(line.message).toContain("已选 28→29");
  });

  it("classifies runtime heuristics: command echo, exit codes, plain text", () => {
    expect(parseLogLine("monitor", "$ python monitor.py --once", "12:00:00").level).toBe("debug");
    expect(parseLogLine("monitor", "exit=0").level).toBe("info");
    expect(parseLogLine("monitor", "exit=1").level).toBe("error");
    expect(parseLogLine("monitor", "exit=-").level).toBe("warn");
    const plain = parseLogLine("bootstrap", "已保存 catalog.json", "12:00:01");
    expect(plain.level).toBe("info");
    expect(plain.time).toBe("12:00:01");
  });
});

describe("bootstrap result handling", () => {
  it("parses the structured result line even with a log prefix", () => {
    const line = '[bootstrap-result] {"ok": false, "reason": "term_mismatch", "message": "学期不一致"}';
    expect(parseBootstrapResult(line)).toMatchObject({ ok: false, reason: "term_mismatch" });
    expect(parseBootstrapResult("INFO [bootstrap] 普通日志")).toBeNull();
    expect(parseBootstrapResult("[bootstrap-result] {broken")).toBeNull();
  });

  it("builds a notice from the failure reason", () => {
    expect(bootstrapFailureNotice({ ok: false, reason: "closed", message: "未开放" }, 3)).toEqual({
      title: "教务网站选课未开放",
      message: "未开放",
    });
  });

  it("falls back to a generic hint when the process gave no result", () => {
    const notice = bootstrapFailureNotice(null, 1);
    expect(notice.title).toBe("获取全量课程失败");
    expect(notice.message).toContain("exit=1");
    expect(notice.message).toContain("学期");
  });
});
