using System.Text.Json;
using System.Text.Json.Serialization;

namespace JiaoWoXuan.Core;

// 与 ng_service 协议 v1 的数据结构一一对应(见 ng/DESIGN.md)。
// 显式标注 JsonPropertyName,不使用全局命名策略:字典键(教学班 id、方案名)不能被改写。

public static class Json
{
    public static readonly JsonSerializerOptions Options = new()
    {
        PropertyNameCaseInsensitive = false,
        NumberHandling = JsonNumberHandling.AllowReadingFromString,
        Converters = { new JsonStringEnumConverter(JsonNamingPolicy.SnakeCaseLower) },
    };
}

public enum AutoSwapState { Off, DryRun, Enabled }

public enum Availability { Open, Full, Unknown }

public enum RatingStatus { Rated, Empty, TeacherUnrated, NotFound, Failed, Unknown }

public enum LogLevel { Info, Warn, Error, Debug }

/// 状态标签的语气,UI 层据此取颜色。
public enum Tone { Neutral, Accent, Success, Danger, Warning }

public static class Labels
{
    public static string Of(AutoSwapState state) => state switch
    {
        AutoSwapState.Enabled => "真实启用",
        AutoSwapState.DryRun => "演练",
        _ => "关闭",
    };

    public static string Of(RatingStatus status) => status switch
    {
        RatingStatus.Rated => "课程评价",
        RatingStatus.Empty => "暂无评价",
        RatingStatus.TeacherUnrated => "本班老师无评价",
        RatingStatus.NotFound => "社区未收录",
        RatingStatus.Failed => "评价获取失败",
        _ => "尚未获取评价",
    };

    public static string Of(LogLevel level) => level switch
    {
        LogLevel.Warn => "警告",
        LogLevel.Error => "错误",
        LogLevel.Debug => "调试",
        _ => "信息",
    };

    /// 未同步的用户字段显示为"未同步",而不是假定抓取成功。
    public static string UserValue(string? value)
    {
        var text = (value ?? "").Trim();
        return text.Length == 0 || text == "-" ? "未同步" : text;
    }

    public static string ShortId(string? value)
    {
        if (string.IsNullOrEmpty(value)) return "-";
        return value.Length > 18 ? $"{value[..8]}…{value[^6..]}" : value;
    }
}

public sealed class HelloInfo
{
    [JsonPropertyName("protocol")] public int Protocol { get; set; }
    [JsonPropertyName("version")] public string Version { get; set; } = "";
    [JsonPropertyName("release_mode")] public bool ReleaseMode { get; set; }
    [JsonPropertyName("data_dir")] public string DataDir { get; set; } = "";
    [JsonPropertyName("platform")] public string Platform { get; set; } = "";
    [JsonPropertyName("running")] public List<string> Running { get; set; } = [];
}

public sealed class Metrics
{
    [JsonPropertyName("queries")] public int Queries { get; set; }
    [JsonPropertyName("groups")] public int Groups { get; set; }
    [JsonPropertyName("snapshot")] public int Snapshot { get; set; }
    [JsonPropertyName("watched")] public int Watched { get; set; }
    [JsonPropertyName("open_courses")] public int OpenCourses { get; set; }
    [JsonPropertyName("interval")] public string Interval { get; set; } = "";
    [JsonPropertyName("auto_swap")] public AutoSwapState AutoSwap { get; set; }
}

public sealed record SettingsPayload
{
    [JsonPropertyName("jaccount_user")] public string JaccountUser { get; set; } = "";
    [JsonPropertyName("jaccount_pass")] public string JaccountPass { get; set; } = "";
    [JsonPropertyName("course_plus_password")] public string CoursePlusPassword { get; set; } = "";
    [JsonPropertyName("has_jaccount_pass")] public bool? HasJaccountPass { get; set; }
    [JsonPropertyName("has_course_plus_password")] public bool? HasCoursePlusPassword { get; set; }
    [JsonPropertyName("poll_min")] public int PollMin { get; set; } = 60;
    [JsonPropertyName("poll_max")] public int PollMax { get; set; } = 120;
    [JsonPropertyName("email_enabled")] public bool EmailEnabled { get; set; } = true;
    [JsonPropertyName("smtp_host")] public string SmtpHost { get; set; } = "";
    [JsonPropertyName("smtp_port")] public int SmtpPort { get; set; } = 465;
    [JsonPropertyName("smtp_user")] public string SmtpUser { get; set; } = "";
    [JsonPropertyName("smtp_pass")] public string SmtpPass { get; set; } = "";
    [JsonPropertyName("has_smtp_pass")] public bool? HasSmtpPass { get; set; }
    [JsonPropertyName("smtp_pass_fallback")] public bool? SmtpPassFallback { get; set; }
    [JsonPropertyName("secret_backend")] public string? SecretBackend { get; set; }
    [JsonPropertyName("mail_from")] public string MailFrom { get; set; } = "";
    [JsonPropertyName("mail_to")] public string MailTo { get; set; } = "";

    /// 发往 settings.save 的参数(密码留空表示不修改)。
    public Dictionary<string, object?> ToRequest() => new()
    {
        ["jaccount_user"] = JaccountUser,
        ["jaccount_pass"] = JaccountPass,
        ["course_plus_password"] = CoursePlusPassword,
        ["poll_min"] = PollMin,
        ["poll_max"] = PollMax,
        ["email_enabled"] = EmailEnabled,
        ["smtp_host"] = SmtpHost,
        ["smtp_port"] = SmtpPort,
        ["smtp_user"] = SmtpUser,
        ["smtp_pass"] = SmtpPass,
        ["mail_from"] = MailFrom,
        ["mail_to"] = MailTo,
    };
}

public sealed class Onboarding
{
    [JsonPropertyName("completed")] public bool Completed { get; set; }
    [JsonPropertyName("has_account")] public bool HasAccount { get; set; }
    [JsonPropertyName("catalog_ready")] public bool CatalogReady { get; set; }
}

public sealed class UserInfo
{
    [JsonPropertyName("name")] public string Name { get; set; } = "";
    [JsonPropertyName("student_id")] public string StudentId { get; set; } = "";
    [JsonPropertyName("class_name")] public string ClassName { get; set; } = "";
    [JsonPropertyName("major")] public string Major { get; set; } = "";
    [JsonPropertyName("term")] public string Term { get; set; } = "";
    [JsonPropertyName("catalog_fetched_at")] public string? CatalogFetchedAt { get; set; }
}

public sealed class CourseRating
{
    [JsonPropertyName("status")] public RatingStatus Status { get; set; } = RatingStatus.Unknown;
    [JsonPropertyName("score")] public double? Score { get; set; }
    [JsonPropertyName("count")] public int? Count { get; set; }
    [JsonPropertyName("teacher")] public string? Teacher { get; set; }
    [JsonPropertyName("semester")] public string? Semester { get; set; }
    [JsonPropertyName("updated_at")] public string? UpdatedAt { get; set; }
    [JsonPropertyName("message")] public string? Message { get; set; }

    public string ScoreText => Score is { } s && double.IsFinite(s) ? s.ToString("0.0") : "-";

    /// 排序用:只有 rated 才参与分数排序。
    public double? SortScore => Status == RatingStatus.Rated ? Score : null;
}

public sealed class CourseRow
{
    [JsonPropertyName("jxb_id")] public string JxbId { get; set; } = "";
    [JsonPropertyName("title")] public string Title { get; set; } = "";
    [JsonPropertyName("class_name")] public string ClassName { get; set; } = "";
    [JsonPropertyName("summary")] public string Summary { get; set; } = "";
    [JsonPropertyName("detail")] public string Detail { get; set; } = "";
    [JsonPropertyName("teachers")] public string Teachers { get; set; } = "";
    [JsonPropertyName("schedule")] public List<string> Schedule { get; set; } = [];
    [JsonPropertyName("locations")] public List<string> Locations { get; set; } = [];
    [JsonPropertyName("search_text")] public string SearchText { get; set; } = "";
    [JsonPropertyName("seat_text")] public string SeatText { get; set; } = "";
    [JsonPropertyName("availability")] public Availability Availability { get; set; } = Availability.Unknown;
    [JsonPropertyName("availability_text")] public string AvailabilityText { get; set; } = "";
    [JsonPropertyName("group")] public string? Group { get; set; }
    [JsonPropertyName("chosen")] public bool Chosen { get; set; }
    [JsonPropertyName("category")] public string Category { get; set; } = "";
    [JsonPropertyName("rating_text")] public string RatingText { get; set; } = "";
    [JsonPropertyName("rating")] public CourseRating Rating { get; set; } = new();
    [JsonPropertyName("kch")] public string? Kch { get; set; }
    [JsonPropertyName("sksj")] public string? Sksj { get; set; }

    public string FirstSchedule => Schedule.Count > 0 ? Schedule[0] : "时间未定";
    public string StatusText => Chosen ? "已选" : AvailabilityText;
    public Tone StatusTone => Chosen ? Tone.Accent : Availability == Availability.Open ? Tone.Success : Tone.Neutral;
    public bool IsRated => Rating.Status == RatingStatus.Rated;
    public string KchText => Kch ?? "-";
    public string GroupText => Group ?? "";
    public string ScheduleText => Schedule.Count > 0 ? string.Join("\n", Schedule) : "-";
    public string LocationText => Locations.Count > 0 ? string.Join("\n", Locations) : "-";
}

public sealed class ConflictMark
{
    [JsonPropertyName("status")] public string Status { get; set; } = "unknown";
    [JsonPropertyName("with")] public string? With { get; set; }
    [JsonPropertyName("detail")] public string? Detail { get; set; }

    public bool IsConflict => Status == "conflict";
    public string Note => IsConflict ? $"与已选 {With ?? "?"} 冲突：{Detail}" : "时间数据不全，无法判断冲突";
    public string Badge => IsConflict ? "冲突·不会选" : "时间未知·不会选";
}

public sealed class PriorityGroup
{
    [JsonPropertyName("name")] public string Name { get; set; } = "";
    [JsonPropertyName("is_pe")] public bool IsPe { get; set; }
    [JsonPropertyName("priority")] public List<string> Priority { get; set; } = [];
    [JsonPropertyName("held")] public string? Held { get; set; }
    [JsonPropertyName("held_label")] public string HeldLabel { get; set; } = "-";
    [JsonPropertyName("watched_count")] public int WatchedCount { get; set; }
    [JsonPropertyName("fatal")] public bool Fatal { get; set; }
    [JsonPropertyName("conflicts")] public Dictionary<string, ConflictMark> Conflicts { get; set; } = [];
    [JsonPropertyName("conflict_count")] public int ConflictCount { get; set; }

    public PriorityGroup Clone() => new()
    {
        Name = Name,
        IsPe = IsPe,
        Priority = [.. Priority],
        Held = Held,
        HeldLabel = HeldLabel,
        WatchedCount = WatchedCount,
        Fatal = Fatal,
        Conflicts = new(Conflicts),
        ConflictCount = ConflictCount,
    };

    /// 可保存部分的签名,用于判断方案是否有未保存修改。
    public string PlanSignature => $"{Name}{IsPe}{string.Join('', Priority)}";
}

public sealed class ChosenCourse
{
    [JsonPropertyName("jxb_id")] public string JxbId { get; set; } = "";
    [JsonPropertyName("title")] public string Title { get; set; } = "";
    [JsonPropertyName("class_name")] public string ClassName { get; set; } = "";
    [JsonPropertyName("sksj")] public string? Sksj { get; set; }
    [JsonPropertyName("group")] public string? Group { get; set; }
}

public sealed class TermOption
{
    [JsonPropertyName("key")] public string Key { get; set; } = "";
    [JsonPropertyName("xkxnm")] public string Xkxnm { get; set; } = "";
    [JsonPropertyName("xkxqm")] public string Xkxqm { get; set; } = "";
    [JsonPropertyName("label")] public string Label { get; set; } = "";
    [JsonPropertyName("active")] public bool Active { get; set; }
    [JsonPropertyName("group_count")] public int GroupCount { get; set; }
    [JsonPropertyName("catalog_fetched_at")] public string? CatalogFetchedAt { get; set; }
    [JsonPropertyName("is_site_term")] public bool IsSiteTerm { get; set; }
}

public sealed class SiteTermInfo
{
    [JsonPropertyName("key")] public string? Key { get; set; }
    [JsonPropertyName("label")] public string Label { get; set; } = "";
    [JsonPropertyName("zzxk_open")] public bool ZzxkOpen { get; set; }
    [JsonPropertyName("tjxkbkk_open")] public bool TjxkbkkOpen { get; set; }
    [JsonPropertyName("detected_at")] public string? DetectedAt { get; set; }
    [JsonPropertyName("matches_active")] public bool MatchesActive { get; set; }
}

public sealed class StateRow
{
    [JsonPropertyName("jxb_id")] public string JxbId { get; set; } = "";
    [JsonPropertyName("watched")] public bool Watched { get; set; }
    [JsonPropertyName("group")] public string? Group { get; set; }
    [JsonPropertyName("title")] public string Title { get; set; } = "";
    [JsonPropertyName("summary")] public string Summary { get; set; } = "";
    [JsonPropertyName("seat_text")] public string SeatText { get; set; } = "";
    [JsonPropertyName("open")] public bool? Open { get; set; }

    public string StatusText => Open switch { true => "有空位", false => "已满", _ => "未知" };
    public Tone StatusTone => Open == true ? Tone.Success : Tone.Neutral;
    public string GroupText => Group ?? "-";
}

public sealed class SwapHistoryRow
{
    [JsonPropertyName("timestamp")] public string? Timestamp { get; set; }
    [JsonPropertyName("dry_run")] public bool? DryRun { get; set; }
    [JsonPropertyName("group")] public string? Group { get; set; }
    [JsonPropertyName("target")] public string? Target { get; set; }
    [JsonPropertyName("drop")] public string? Drop { get; set; }
    [JsonPropertyName("ok")] public bool? Ok { get; set; }
    [JsonPropertyName("status")] public string? Status { get; set; }
    [JsonPropertyName("kcmc")] public string? Kcmc { get; set; }

    public string ModeText => DryRun == true ? "演练" : "真实";
    public string ResultText => Ok == true ? "成功" : Status ?? "失败";
    public string CourseText => Kcmc ?? Labels.ShortId(Target);
    public string TimestampText => Timestamp ?? "-";
    public string GroupText => Group ?? "-";
    public Tone ResultTone => Ok == true ? Tone.Success : Tone.Danger;
}

public sealed class SwapState
{
    [JsonPropertyName("completed")] public List<string> Completed { get; set; } = [];
    [JsonPropertyName("fatal")] public List<string> Fatal { get; set; } = [];
    [JsonPropertyName("fatal_groups")] public List<string> FatalGroups { get; set; } = [];
}

public sealed class Snapshot
{
    [JsonPropertyName("generated_at")] public string GeneratedAt { get; set; } = "";
    [JsonPropertyName("metrics")] public Metrics Metrics { get; set; } = new();
    [JsonPropertyName("settings")] public SettingsPayload Settings { get; set; } = new();
    [JsonPropertyName("onboarding")] public Onboarding Onboarding { get; set; } = new();
    [JsonPropertyName("user")] public UserInfo User { get; set; } = new();
    [JsonPropertyName("terms")] public List<TermOption> Terms { get; set; } = [];
    [JsonPropertyName("active_term")] public string ActiveTerm { get; set; } = "";
    [JsonPropertyName("site_term")] public SiteTermInfo? SiteTerm { get; set; }
    [JsonPropertyName("groups")] public List<PriorityGroup> Groups { get; set; } = [];
    [JsonPropertyName("courses")] public List<CourseRow> Courses { get; set; } = [];
    [JsonPropertyName("choosed")] public List<ChosenCourse> Choosed { get; set; } = [];
    [JsonPropertyName("choosed_at")] public string? ChoosedAt { get; set; }
    [JsonPropertyName("state_rows")] public List<StateRow> StateRows { get; set; } = [];
    [JsonPropertyName("swap_state")] public SwapState SwapState { get; set; } = new();
    [JsonPropertyName("swap_history")] public List<SwapHistoryRow> SwapHistory { get; set; } = [];
    [JsonPropertyName("categories")] public List<string> Categories { get; set; } = [];
    [JsonPropertyName("running")] public List<string> Running { get; set; } = [];
    [JsonPropertyName("release_mode")] public bool ReleaseMode { get; set; }
}

public sealed class SaveGroupsResult
{
    [JsonPropertyName("ok")] public bool Ok { get; set; }
    [JsonPropertyName("warnings")] public List<string> Warnings { get; set; } = [];
    [JsonPropertyName("duplicates")] public Dictionary<string, List<string>> Duplicates { get; set; } = [];
    [JsonPropertyName("unresolved")] public List<string> Unresolved { get; set; } = [];
    [JsonPropertyName("course_count")] public int CourseCount { get; set; }
}

public sealed class GroupEvaluation
{
    [JsonPropertyName("name")] public string Name { get; set; } = "";
    [JsonPropertyName("held")] public string? Held { get; set; }
    [JsonPropertyName("held_label")] public string HeldLabel { get; set; } = "-";
    [JsonPropertyName("conflicts")] public Dictionary<string, ConflictMark> Conflicts { get; set; } = [];
    [JsonPropertyName("conflict_count")] public int ConflictCount { get; set; }
}

public sealed class GroupsEvaluateResult
{
    [JsonPropertyName("groups")] public List<GroupEvaluation> Groups { get; set; } = [];
}

public sealed class AddCoursesResult
{
    [JsonPropertyName("priority")] public List<string> Priority { get; set; } = [];
    [JsonPropertyName("added")] public List<string> Added { get; set; } = [];
    [JsonPropertyName("warning")] public string? Warning { get; set; }
}

public sealed class LogEntry
{
    [JsonPropertyName("time")] public string Time { get; set; } = "";
    [JsonPropertyName("level")] public LogLevel Level { get; set; }
    [JsonPropertyName("source")] public string Source { get; set; } = "";
    [JsonPropertyName("message")] public string Message { get; set; } = "";

    public string TimeText => string.IsNullOrEmpty(Time) ? "--:--:--" : Time;
    public string LevelText => Labels.Of(Level);
    public Tone LevelTone => Level switch
    {
        LogLevel.Warn => Tone.Warning,
        LogLevel.Error => Tone.Danger,
        LogLevel.Debug => Tone.Neutral,
        _ => Tone.Accent,
    };
}

public sealed class LogCounts
{
    [JsonPropertyName("all")] public int All { get; set; }
    [JsonPropertyName("info")] public int Info { get; set; }
    [JsonPropertyName("warn")] public int Warn { get; set; }
    [JsonPropertyName("error")] public int Error { get; set; }
    [JsonPropertyName("debug")] public int Debug { get; set; }

    public int For(LogLevel? level) => level switch
    {
        null => All,
        LogLevel.Info => Info,
        LogLevel.Warn => Warn,
        LogLevel.Error => Error,
        LogLevel.Debug => Debug,
        _ => 0,
    };
}

public sealed class LogsQueryResult
{
    [JsonPropertyName("entries")] public List<LogEntry> Entries { get; set; } = [];
    [JsonPropertyName("counts")] public LogCounts Counts { get; set; } = new();
}

public sealed record Notice(
    [property: JsonPropertyName("title")] string Title,
    [property: JsonPropertyName("message")] string Message);

public sealed class BootstrapResult
{
    [JsonPropertyName("ok")] public bool Ok { get; set; }
    [JsonPropertyName("action")] public string? Action { get; set; }
    [JsonPropertyName("reason")] public string? Reason { get; set; }
    [JsonPropertyName("message")] public string? Message { get; set; }
    [JsonPropertyName("site_term")] public JsonElement? SiteTerm { get; set; }

    public string? SiteTermLabel =>
        SiteTerm is { ValueKind: JsonValueKind.Object } site && site.TryGetProperty("label", out var label)
            ? label.GetString()
            : null;
}

public sealed class ProcessExit
{
    [JsonPropertyName("task")] public string Task { get; set; } = "";
    [JsonPropertyName("code")] public int? Code { get; set; }
    [JsonPropertyName("stopped")] public bool Stopped { get; set; }
    [JsonPropertyName("notice")] public Notice? Notice { get; set; }
    [JsonPropertyName("result")] public BootstrapResult? Result { get; set; }
}

public sealed class OkResult
{
    [JsonPropertyName("ok")] public bool Ok { get; set; }
}

public sealed class TestEmailResult
{
    [JsonPropertyName("ok")] public bool Ok { get; set; }
    [JsonPropertyName("mail_to")] public string? MailTo { get; set; }
}

public sealed class SwitchTermResult
{
    [JsonPropertyName("ok")] public bool Ok { get; set; }
    [JsonPropertyName("active_term")] public string ActiveTerm { get; set; } = "";
}

public sealed class RunningResult
{
    [JsonPropertyName("running")] public List<string> Running { get; set; } = [];
}
