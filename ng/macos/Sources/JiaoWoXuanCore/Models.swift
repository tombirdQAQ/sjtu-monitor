import Foundation

// 与 ng_service 协议 v1 的数据结构一一对应(见 ng/DESIGN.md 与 src/api.ts)。
// 字段名保持后端的 snake_case,通过 CodingKeys 映射,不使用全局 keyDecodingStrategy:
// 字典键(教学班 id、方案名)不能被改写。

public enum AutoSwapState: String, Codable, Sendable {
    case off
    case dryRun = "dry_run"
    case enabled

    public var label: String {
        switch self {
        case .off: "关闭"
        case .dryRun: "通知"
        case .enabled: "启用"
        }
    }
}

public enum Availability: String, Codable, Sendable {
    case open, full, unknown
}

public struct HelloInfo: Codable, Sendable {
    public var protocolVersion: Int
    public var version: String
    public var releaseMode: Bool
    public var dataDir: String
    public var platform: String
    public var running: [String]

    enum CodingKeys: String, CodingKey {
        case protocolVersion = "protocol"
        case version
        case releaseMode = "release_mode"
        case dataDir = "data_dir"
        case platform, running
    }
}

public struct Metrics: Codable, Sendable {
    public var queries: Int
    public var groups: Int
    public var snapshot: Int
    public var watched: Int
    public var openCourses: Int
    public var interval: String
    public var autoSwap: AutoSwapState

    enum CodingKeys: String, CodingKey {
        case queries, groups, snapshot, watched, interval
        case openCourses = "open_courses"
        case autoSwap = "auto_swap"
    }
}

public struct SettingsPayload: Codable, Sendable, Equatable {
    public var jaccountUser: String = ""
    public var jaccountPass: String = ""
    public var coursePlusPassword: String = ""
    public var hasJaccountPass: Bool? = nil
    public var hasCoursePlusPassword: Bool? = nil
    public var pollMin: Int = 60
    public var pollMax: Int = 120
    public var emailEnabled: Bool = true
    public var smtpHost: String = ""
    public var smtpPort: Int = 465
    public var smtpUser: String = ""
    public var smtpPass: String = ""
    public var hasSmtpPass: Bool? = nil
    public var smtpPassFallback: Bool? = nil
    public var secretBackend: String? = nil
    public var mailFrom: String = ""
    public var mailTo: String = ""

    public init() {}

    enum CodingKeys: String, CodingKey {
        case jaccountUser = "jaccount_user"
        case jaccountPass = "jaccount_pass"
        case coursePlusPassword = "course_plus_password"
        case hasJaccountPass = "has_jaccount_pass"
        case hasCoursePlusPassword = "has_course_plus_password"
        case pollMin = "poll_min"
        case pollMax = "poll_max"
        case emailEnabled = "email_enabled"
        case smtpHost = "smtp_host"
        case smtpPort = "smtp_port"
        case smtpUser = "smtp_user"
        case smtpPass = "smtp_pass"
        case hasSmtpPass = "has_smtp_pass"
        case smtpPassFallback = "smtp_pass_fallback"
        case secretBackend = "secret_backend"
        case mailFrom = "mail_from"
        case mailTo = "mail_to"
    }

    /// 发往 settings.save 的参数(密码留空表示不修改)。
    public var requestParams: [String: Any] {
        [
            "jaccount_user": jaccountUser,
            "jaccount_pass": jaccountPass,
            "course_plus_password": coursePlusPassword,
            "poll_min": pollMin,
            "poll_max": pollMax,
            "email_enabled": emailEnabled,
            "smtp_host": smtpHost,
            "smtp_port": smtpPort,
            "smtp_user": smtpUser,
            "smtp_pass": smtpPass,
            "mail_from": mailFrom,
            "mail_to": mailTo,
        ]
    }
}

public struct Onboarding: Codable, Sendable {
    public var completed: Bool
    public var hasAccount: Bool
    public var catalogReady: Bool

    enum CodingKeys: String, CodingKey {
        case completed
        case hasAccount = "has_account"
        case catalogReady = "catalog_ready"
    }
}

public struct UserInfo: Codable, Sendable {
    public var name: String
    public var studentId: String
    public var className: String
    public var major: String
    public var term: String
    public var catalogFetchedAt: String?

    enum CodingKeys: String, CodingKey {
        case name, major, term
        case studentId = "student_id"
        case className = "class_name"
        case catalogFetchedAt = "catalog_fetched_at"
    }
}

public enum RatingStatus: String, Codable, Sendable {
    case rated, empty, unknown, failed
    case teacherUnrated = "teacher_unrated"
    case notFound = "not_found"

    public var label: String {
        switch self {
        case .rated: "课程评价"
        case .empty: "暂无评价"
        case .teacherUnrated: "本班老师无评价"
        case .notFound: "社区未收录"
        case .failed: "评价获取失败"
        case .unknown: "尚未获取评价"
        }
    }
}

public struct CourseRating: Codable, Sendable, Hashable {
    public var status: RatingStatus
    public var score: Double?
    public var count: Int?
    public var teacher: String?
    public var semester: String?
    public var updatedAt: String?
    public var message: String?

    enum CodingKeys: String, CodingKey {
        case status, score, count, teacher, semester, message
        case updatedAt = "updated_at"
    }

    public var scoreText: String {
        guard let score, score.isFinite else { return "-" }
        return String(format: "%.1f", score)
    }

    /// 排序用:只有 rated 才参与分数排序(与 courseLogic.sortCourses 一致)。
    public var sortScore: Double? { status == .rated ? score : nil }
}

public struct CourseRow: Codable, Sendable, Identifiable, Hashable {
    public var jxbId: String
    public var title: String
    public var className: String
    public var summary: String
    public var detail: String
    public var teachers: String
    public var schedule: [String]
    public var locations: [String]
    public var searchText: String
    public var seatText: String
    public var availability: Availability
    public var availabilityText: String
    public var group: String?
    public var chosen: Bool
    public var category: String
    public var ratingText: String
    public var rating: CourseRating
    public var kch: String?
    public var sksj: String?

    public var id: String { jxbId }

    enum CodingKeys: String, CodingKey {
        case title, summary, detail, teachers, schedule, locations, availability, group
        case chosen, category, rating, kch, sksj
        case jxbId = "jxb_id"
        case className = "class_name"
        case searchText = "search_text"
        case seatText = "seat_text"
        case availabilityText = "availability_text"
        case ratingText = "rating_text"
    }

    public var firstSchedule: String { schedule.first ?? "时间未定" }
}

public struct ConflictMark: Codable, Sendable, Hashable {
    public enum Status: String, Codable, Sendable { case conflict, unknown }
    public var status: Status
    public var with: String?
    public var detail: String?

    public var note: String {
        status == .conflict ? "与已选 \(with ?? "?") 冲突：\(detail ?? "")" : "时间数据不全，无法判断冲突"
    }

    public var badge: String { status == .conflict ? "冲突·不会选" : "时间未知·不会选" }
}

public struct GroupMember: Codable, Sendable, Hashable {
    public var jxbId: String
    public var label: String
    public var detail: String
    public var chosen: Bool
    public var watched: Bool
    public var availability: Availability

    enum CodingKeys: String, CodingKey {
        case label, detail, chosen, watched, availability
        case jxbId = "jxb_id"
    }
}

public struct PriorityGroup: Codable, Sendable, Identifiable, Hashable {
    public var name: String
    public var isPe: Bool
    public var priority: [String]
    public var held: String?
    public var heldLabel: String
    public var watchedCount: Int
    public var fatal: Bool
    public var members: [GroupMember]
    public var conflicts: [String: ConflictMark]
    public var conflictCount: Int

    public var id: String { name }

    public init(name: String) {
        self.name = name
        isPe = false
        priority = []
        held = nil
        heldLabel = "-"
        watchedCount = 0
        fatal = false
        members = []
        conflicts = [:]
        conflictCount = 0
    }

    enum CodingKeys: String, CodingKey {
        case name, priority, held, fatal, members, conflicts
        case isPe = "is_pe"
        case heldLabel = "held_label"
        case watchedCount = "watched_count"
        case conflictCount = "conflict_count"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = try c.decode(String.self, forKey: .name)
        isPe = try c.decode(Bool.self, forKey: .isPe)
        priority = try c.decode([String].self, forKey: .priority)
        held = try c.decodeIfPresent(String.self, forKey: .held)
        heldLabel = try c.decodeIfPresent(String.self, forKey: .heldLabel) ?? "-"
        watchedCount = try c.decodeIfPresent(Int.self, forKey: .watchedCount) ?? 0
        fatal = try c.decodeIfPresent(Bool.self, forKey: .fatal) ?? false
        members = try c.decodeIfPresent([GroupMember].self, forKey: .members) ?? []
        conflicts = try c.decodeIfPresent([String: ConflictMark].self, forKey: .conflicts) ?? [:]
        conflictCount = try c.decodeIfPresent(Int.self, forKey: .conflictCount) ?? conflicts.count
    }

    /// 可保存的部分;用于判断方案是否有未保存修改。
    public struct Plan: Equatable, Sendable {
        public var name: String
        public var isPe: Bool
        public var priority: [String]
    }

    public var plan: Plan { Plan(name: name, isPe: isPe, priority: priority) }
}

public struct ChosenCourse: Codable, Sendable, Hashable {
    public var jxbId: String
    public var title: String
    public var className: String
    public var sksj: String?
    public var group: String?

    enum CodingKeys: String, CodingKey {
        case title, sksj, group
        case jxbId = "jxb_id"
        case className = "class_name"
    }
}

public struct TermOption: Codable, Sendable, Identifiable, Hashable {
    public var key: String
    public var xkxnm: String
    public var xkxqm: String
    public var label: String
    public var active: Bool
    public var groupCount: Int
    public var catalogFetchedAt: String?
    public var isSiteTerm: Bool

    public var id: String { key }

    enum CodingKeys: String, CodingKey {
        case key, xkxnm, xkxqm, label, active
        case groupCount = "group_count"
        case catalogFetchedAt = "catalog_fetched_at"
        case isSiteTerm = "is_site_term"
    }
}

public struct SiteTermInfo: Codable, Sendable, Hashable {
    public var key: String?
    public var label: String
    public var zzxkOpen: Bool
    public var tjxkbkkOpen: Bool
    public var detectedAt: String?
    public var matchesActive: Bool

    enum CodingKeys: String, CodingKey {
        case key, label
        case zzxkOpen = "zzxk_open"
        case tjxkbkkOpen = "tjxkbkk_open"
        case detectedAt = "detected_at"
        case matchesActive = "matches_active"
    }
}

public struct StateRow: Codable, Sendable, Identifiable, Hashable {
    public var jxbId: String
    public var watched: Bool
    public var group: String?
    public var title: String
    public var summary: String
    public var seatText: String
    public var open: Bool?

    public var id: String { jxbId }

    enum CodingKeys: String, CodingKey {
        case watched, group, title, summary, open
        case jxbId = "jxb_id"
        case seatText = "seat_text"
    }
}

public struct SwapHistoryRow: Codable, Sendable, Hashable {
    public var timestamp: String?
    public var dryRun: Bool?
    public var group: String?
    public var target: String?
    public var drop: String?
    public var ok: Bool?
    public var status: String?
    public var kcmc: String?

    enum CodingKeys: String, CodingKey {
        case timestamp, group, target, drop, ok, status, kcmc
        case dryRun = "dry_run"
    }
}

public struct SwapState: Codable, Sendable {
    public var completed: [String]
    public var fatal: [String]
    public var fatalGroups: [String]

    enum CodingKeys: String, CodingKey {
        case completed, fatal
        case fatalGroups = "fatal_groups"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        completed = try c.decodeIfPresent([String].self, forKey: .completed) ?? []
        fatal = try c.decodeIfPresent([String].self, forKey: .fatal) ?? []
        fatalGroups = try c.decodeIfPresent([String].self, forKey: .fatalGroups) ?? []
    }
}

public struct Snapshot: Codable, Sendable {
    public var generatedAt: String
    public var metrics: Metrics
    public var settings: SettingsPayload
    public var onboarding: Onboarding
    public var user: UserInfo
    public var terms: [TermOption]
    public var activeTerm: String
    public var siteTerm: SiteTermInfo?
    public var groups: [PriorityGroup]
    public var courses: [CourseRow]
    public var choosed: [ChosenCourse]
    public var choosedAt: String?
    public var stateRows: [StateRow]
    public var swapState: SwapState
    public var swapHistory: [SwapHistoryRow]
    public var categories: [String]
    public var running: [String]
    public var releaseMode: Bool

    enum CodingKeys: String, CodingKey {
        case metrics, settings, onboarding, user, terms, groups, courses, choosed, categories, running
        case generatedAt = "generated_at"
        case activeTerm = "active_term"
        case siteTerm = "site_term"
        case choosedAt = "choosed_at"
        case stateRows = "state_rows"
        case swapState = "swap_state"
        case swapHistory = "swap_history"
        case releaseMode = "release_mode"
    }
}

public struct SaveGroupsResult: Codable, Sendable {
    public var ok: Bool
    public var warnings: [String]
    public var duplicates: [String: [String]]
    public var unresolved: [String]
    public var courseCount: Int

    enum CodingKeys: String, CodingKey {
        case ok, warnings, duplicates, unresolved
        case courseCount = "course_count"
    }
}

public struct GroupEvaluation: Codable, Sendable {
    public var name: String
    public var held: String?
    public var heldLabel: String
    public var conflicts: [String: ConflictMark]
    public var conflictCount: Int

    enum CodingKeys: String, CodingKey {
        case name, held, conflicts
        case heldLabel = "held_label"
        case conflictCount = "conflict_count"
    }
}

public struct GroupsEvaluateResult: Codable, Sendable {
    public var groups: [GroupEvaluation]
}

public struct AddCoursesResult: Codable, Sendable {
    public var priority: [String]
    public var added: [String]
    public var warning: String?
}

public enum LogLevel: String, Codable, Sendable, CaseIterable, Identifiable {
    case info, warn, error, debug
    public var id: String { rawValue }
}

public struct LogEntry: Codable, Sendable, Hashable {
    public var time: String
    public var level: LogLevel
    public var source: String
    public var message: String
}

public struct LogCounts: Codable, Sendable {
    public var all: Int
    public var info: Int
    public var warn: Int
    public var error: Int
    public var debug: Int

    public static let zero = LogCounts(all: 0, info: 0, warn: 0, error: 0, debug: 0)

    public func count(for level: LogLevel?) -> Int {
        switch level {
        case nil: all
        case .info: info
        case .warn: warn
        case .error: error
        case .debug: debug
        }
    }
}

public struct LogsQueryResult: Codable, Sendable {
    public var entries: [LogEntry]
    public var counts: LogCounts

    public init(entries: [LogEntry], counts: LogCounts) {
        self.entries = entries
        self.counts = counts
    }
}

public struct Notice: Codable, Sendable, Hashable, Identifiable {
    public var title: String
    public var message: String
    public var id: String { title + message }

    public init(title: String, message: String) {
        self.title = title
        self.message = message
    }
}

public struct ProcessExit: Codable, Sendable {
    public var task: String
    public var code: Int?
    public var stopped: Bool
    public var notice: Notice?
    public var result: BootstrapResult?
}

public struct BootstrapResult: Codable, Sendable {
    public var ok: Bool
    public var action: String?
    public var reason: String?
    public var message: String?
    public var siteTerm: SiteTermLabel?

    public struct SiteTermLabel: Codable, Sendable {
        public var label: String?
    }

    enum CodingKeys: String, CodingKey {
        case ok, action, reason, message
        case siteTerm = "site_term"
    }
}

public struct OkResult: Codable, Sendable {
    public var ok: Bool
}

public struct TestEmailResult: Codable, Sendable {
    public var ok: Bool
    public var mailTo: String?

    enum CodingKeys: String, CodingKey {
        case ok
        case mailTo = "mail_to"
    }
}

public struct SwitchTermResult: Codable, Sendable {
    public var ok: Bool
    public var activeTerm: String

    enum CodingKeys: String, CodingKey {
        case ok
        case activeTerm = "active_term"
    }
}

public struct RunningResult: Codable, Sendable {
    public var running: [String]
}
