import type { ChosenCourse, CourseRow } from "./api";

export type CourseSort = "catalog" | "name" | "rating";

export function formatRatingScore(score: number | null | undefined): string {
  return typeof score === "number" && Number.isFinite(score) ? score.toFixed(1) : "-";
}

export function sortCourses(courses: CourseRow[], sort: CourseSort): CourseRow[] {
  if (sort === "catalog") return courses;
  return [...courses].sort((left, right) => {
    if (sort === "rating") {
      const leftScore = left.rating.status === "rated" ? left.rating.score : null;
      const rightScore = right.rating.status === "rated" ? right.rating.score : null;
      if (leftScore !== rightScore) {
        if (leftScore === null) return 1;
        if (rightScore === null) return -1;
        return rightScore - leftScore;
      }
    }
    return left.title.localeCompare(right.title, "zh-CN", {
      numeric: true,
      sensitivity: "base",
    }) || left.jxb_id.localeCompare(right.jxb_id);
  });
}

const weekdayNumbers: Record<string, number> = {
  一: 1,
  二: 2,
  三: 3,
  四: 4,
  五: 5,
  六: 6,
  日: 7,
  天: 7,
};

const numberWeekdays: Record<number, string> = {
  1: "一",
  2: "二",
  3: "三",
  4: "四",
  5: "五",
  6: "六",
  7: "日",
};

function expandRange(spec: string): number[] {
  const values = new Set<number>();
  for (const rawToken of spec.split(",")) {
    const token = rawToken.trim();
    if (!token) continue;
    const [rawStart, rawEnd] = token.split("-", 2);
    const start = Number(rawStart);
    const end = rawEnd === undefined ? start : Number(rawEnd);
    if (!Number.isInteger(start) || !Number.isInteger(end)) continue;
    for (let value = start; value <= end; value += 1) values.add(value);
  }
  return [...values];
}

function expandWeeks(spec: string): number[] {
  const values = new Set<number>();
  for (const rawToken of spec.split(",")) {
    const match = rawToken.trim().match(/^(\d+)(?:-(\d+))?周(?:\((单|双)\))?$/);
    if (!match) continue;
    const start = Number(match[1]);
    const end = match[2] ? Number(match[2]) : start;
    const parity = match[3];
    for (let week = start; week <= end; week += 1) {
      if (parity === "单" && week % 2 === 0) continue;
      if (parity === "双" && week % 2 === 1) continue;
      values.add(week);
    }
  }
  return [...values];
}

export function parseSchedule(schedule?: string | null): Set<string> | null {
  const text = String(schedule || "").trim();
  if (!text || ["--", "不排教室", "待定"].includes(text)) return null;
  const slots = new Set<string>();
  const pattern = /星期([一二三四五六日天])第([\d,-]+)节(?:\{([^}]*)\})?/g;
  for (const segment of text.split(/<br\s*\/?>|\r?\n/i)) {
    pattern.lastIndex = 0;
    const match = pattern.exec(segment.trim());
    if (!match) continue;
    const day = weekdayNumbers[match[1]];
    const periods = expandRange(match[2]);
    const weeks = match[3] ? expandWeeks(match[3]) : [];
    for (const week of weeks) {
      for (const period of periods) slots.add(`${day}:${week}:${period}`);
    }
  }
  return slots.size > 0 ? slots : null;
}

export function scheduleConflict(
  first?: string | null,
  second?: string | null,
): { conflict: boolean; detail?: string } | null {
  const firstSlots = parseSchedule(first);
  const secondSlots = parseSchedule(second);
  if (!firstSlots || !secondSlots) return null;
  const sortedSlots = [...firstSlots].sort((left, right) => {
    const leftParts = left.split(":").map(Number);
    const rightParts = right.split(":").map(Number);
    return leftParts[0] - rightParts[0]
      || leftParts[1] - rightParts[1]
      || leftParts[2] - rightParts[2];
  });
  for (const slot of sortedSlots) {
    if (!secondSlots.has(slot)) continue;
    const [day, week, period] = slot.split(":").map(Number);
    return {
      conflict: true,
      detail: `周${numberWeekdays[day] || day} 第${period}节 (第${week}周)`,
    };
  }
  return { conflict: false };
}

export type LogLevel = "info" | "warn" | "error" | "debug";

export interface ParsedLogLine {
  time: string;
  level: LogLevel;
  source: string;
  message: string;
}

const levelTokens: Record<string, LogLevel> = {
  DEBUG: "debug",
  INFO: "info",
  WARN: "warn",
  WARNING: "warn",
  ERROR: "error",
  CRITICAL: "error",
};

const changeFieldLabels: Record<string, string> = {
  yxzrs: "已选",
  xzzrs: "选中",
  cxrs: "抽选人数",
  jxbrs: "班人数",
  jxbxzrs: "班选中",
  syddrs: "剩余",
  jxbrl: "容量",
  yl: "总容量",
  krrl: "可容",
  cxrl: "抽选容量",
};

function formatChangeRecord(record: Record<string, unknown>): { level: LogLevel; message: string } {
  const name = String(record.kcmc || "");
  const jxb = String(record.jxbmc || "");
  const label = `${jxb} ${name}`.trim();
  const kind = String(record.kind || "");
  if (kind === "spot_open") {
    return { level: "warn", message: `🔥 [有空位] ${label} — ${String(record.msg || "")}` };
  }
  if (kind === "swap_result") {
    if (record.ok) return { level: "info", message: `✅ [换课成功] ${label} 已抢到` };
    const status = String(record.status || "");
    if (status === "FATAL_LOST") {
      return { level: "error", message: `❌ [换课致命错误] ${label} — 旧课退了选不回，需人工处理` };
    }
    return { level: "error", message: `⚠️ [换课失败] ${label} — ${status}` };
  }
  if (kind === "added") return { level: "info", message: `[新增] ${label}` };
  if (kind === "removed") return { level: "info", message: `[移除] ${label}` };
  if (kind === "conflict_skipped") {
    return {
      level: "warn",
      message: `[跳过换课·时间冲突] ${label} — 与「${String(record.conflict_group || "?")}」组冲突: ${String(record.detail || "")}`,
    };
  }
  if (kind === "schedule_unknown_skip") {
    return { level: "warn", message: `[跳过换课·时间未知] ${label} — 无法确认冲突，保守跳过` };
  }
  const changes = record.changes;
  if (changes && typeof changes === "object") {
    const parts = Object.entries(changes as Record<string, [unknown, unknown]>).map(
      ([field, pair]) => `${changeFieldLabels[field] || field} ${pair?.[0]}→${pair?.[1]}`,
    );
    return { level: "info", message: `[变动] ${label} ${parts.join(", ")}` };
  }
  return { level: "info", message: `${kind ? `[${kind}] ` : ""}${label}`.trim() };
}

function inferLevel(text: string): LogLevel {
  if (text.startsWith("$ ")) return "debug";
  const exit = text.match(/^exit=(.+)$/);
  if (exit) return exit[1] === "0" ? "info" : exit[1] === "-" ? "warn" : "error";
  if (text.includes("Traceback (most recent call last)")) return "error";
  if (/\b(ERROR|CRITICAL|FAILED)\b/.test(text) || text.includes("失败") || text.includes("错误")) return "error";
  if (/\bWARN(ING)?\b/.test(text) || text.includes("警告")) return "warn";
  return "info";
}

export function parseLogLine(source: string, text: string, fallbackTime = ""): ParsedLogLine {
  const line = text.trim();
  const stamped = line.match(/^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})(?:[,.]\d+)?\s+(.*)$/s);
  const time = stamped ? stamped[2] : fallbackTime;
  const rest = stamped ? stamped[3] : line;
  const logging = rest.match(/^(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL)\s+(?:\[([^\]]+)\]\s*)?(.*)$/s);
  if (logging) {
    return {
      time,
      level: levelTokens[logging[1]],
      source: logging[2] || source,
      message: logging[3] || rest,
    };
  }
  if (rest.startsWith("{")) {
    try {
      const record = JSON.parse(rest) as Record<string, unknown>;
      const formatted = formatChangeRecord(record);
      return { time, source, ...formatted };
    } catch {
      // Not JSON after all; fall through to the plain-text heuristics.
    }
  }
  return { time, level: inferLevel(rest), source, message: rest };
}

function rawSchedule(course: CourseRow | undefined): string | null {
  if (!course) return null;
  return course.sksj || course.schedule.join("\n") || null;
}

/** 与 timetable.is_unscheduled 一致：空或占位符表示不排课，不占任何时段。 */
export function isUnscheduled(schedule?: string | null): boolean {
  return ["", "--", "不排教室", "待定"].includes(String(schedule ?? "").trim());
}

export interface ConflictMark {
  status: "conflict" | "unknown";
  /** 冲突的已选课程名称 */
  with?: string;
  detail?: string;
}

function chosenLabel(course: ChosenCourse): string {
  return course.class_name ? `${course.title} - ${course.class_name}` : course.title;
}

/** 本组外、占用时段的已选课程(本组已选即将被换掉，不参与比较)。 */
function chosenOutside(groupIds: Iterable<string>, choosed: ChosenCourse[]): ChosenCourse[] {
  const ids = new Set(groupIds);
  return choosed.filter((course) => !ids.has(course.jxb_id) && !isUnscheduled(course.sksj));
}

function markAgainst(schedule: string | null, others: ChosenCourse[]): ConflictMark | null {
  let unknown = false;
  for (const other of others) {
    const verdict = scheduleConflict(schedule, other.sksj);
    if (verdict === null) {
      unknown = true;
      continue;
    }
    if (verdict.conflict) return { status: "conflict", with: chosenLabel(other), detail: verdict.detail };
  }
  return unknown ? { status: "unknown" } : null;
}

/**
 * 与 monitor.conflict_marks 同一规则：组内可能被选择的课程(优先级高于组内最高已选；
 * 组内无已选则整组)若与本组外已选课程时间冲突或无法判断，按规则不会被选择。
 */
export function groupConflictMarks(
  priority: string[],
  courses: CourseRow[],
  choosed: ChosenCourse[],
): Map<string, ConflictMark> {
  const chosenIds = new Set(choosed.map((course) => course.jxb_id));
  const heldIndex = priority.findIndex((id) => chosenIds.has(id));
  const candidates = heldIndex < 0 ? priority : priority.slice(0, heldIndex);
  const others = chosenOutside(priority, choosed);
  const courseById = new Map(courses.map((course) => [course.jxb_id, course]));
  const marks = new Map<string, ConflictMark>();
  if (others.length === 0) return marks;
  for (const id of candidates) {
    const mark = markAgainst(rawSchedule(courseById.get(id)), others);
    if (mark) marks.set(id, mark);
  }
  return marks;
}

export function conflictWarning(
  addedIds: string[],
  targetPriority: string[],
  courses: CourseRow[],
  choosed: ChosenCourse[],
): string | null {
  const courseById = new Map(courses.map((course) => [course.jxb_id, course]));
  const chosenIds = new Set(choosed.map((course) => course.jxb_id));
  const others = chosenOutside([...targetPriority, ...addedIds], choosed);
  const conflicts: string[] = [];
  const unknowns: string[] = [];
  for (const addedId of addedIds) {
    if (chosenIds.has(addedId)) continue;
    const added = courseById.get(addedId);
    const mark = markAgainst(rawSchedule(added), others);
    const title = added?.title || addedId;
    if (mark?.status === "conflict") conflicts.push(`${title} 与已选 ${mark.with}　${mark.detail}`);
    else if (mark?.status === "unknown") unknowns.push(title);
  }
  if (conflicts.length === 0 && unknowns.length === 0) return null;
  return [
    ...(conflicts.length > 0
      ? ["与本组外已选课程时间冲突，按规则不会被选择：", ...conflicts.map((line) => `　${line}`)]
      : []),
    ...(unknowns.length > 0
      ? ["缺少时间数据，无法判断是否冲突，按规则不会被选择：", ...unknowns.map((line) => `　${line}`)]
      : []),
    "已加入方案，可继续保存。",
  ].join("\n");
}

/** bootstrap.py 输出的结构化结果行(bootstrap.RESULT_PREFIX)。 */
export const BOOTSTRAP_RESULT_PREFIX = "[bootstrap-result] ";

export interface BootstrapResult {
  ok: boolean;
  action?: string;
  reason?: "term_mismatch" | "closed" | "empty" | "login" | "network" | "error" | string;
  message?: string;
  site_term?: unknown;
}

export function parseBootstrapResult(line: string): BootstrapResult | null {
  const index = line.indexOf(BOOTSTRAP_RESULT_PREFIX);
  if (index < 0) return null;
  try {
    const value = JSON.parse(line.slice(index + BOOTSTRAP_RESULT_PREFIX.length));
    return value && typeof value === "object" && typeof value.ok === "boolean" ? value : null;
  } catch {
    return null;
  }
}

const bootstrapFailureTitles: Record<string, string> = {
  term_mismatch: "学期与教务网站不一致",
  closed: "教务网站选课未开放",
  empty: "没有获取到课程",
  login: "登录失败",
  session: "登录会话被顶掉",
  network: "无法连接教务网站",
};

/** 抓取进程非 0 退出时的提示；没有结构化结果时给出通用说明。 */
export function bootstrapFailureNotice(
  result: BootstrapResult | null,
  code: number | null | undefined,
  action = "获取全量课程",
): { title: string; message: string } {
  if (result && !result.ok) {
    return {
      title: bootstrapFailureTitles[result.reason || ""] || `${action}失败`,
      message: result.message || `${action}失败，请查看日志页。`,
    };
  }
  return {
    title: `${action}失败`,
    message: `进程异常退出（exit=${code ?? "-"}）。可能不在选课期间、所选学期与教务网站不一致，或教务网站暂时不可达，请查看日志页了解详情。`,
  };
}

