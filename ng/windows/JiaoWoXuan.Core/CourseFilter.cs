using System.Globalization;

namespace JiaoWoXuan.Core;

/// 可点击排序的课程表列。
public enum CourseColumn { Title, Teachers, Schedule, Kch, Seats, Status, Rating, Group }

/// 列头排序状态;Column 为 null 表示目录原始顺序。
public sealed record CourseSortOrder(CourseColumn? Column = null, bool Descending = false)
{
    /// 点击列头:新列从升序开始,同一列在升序 → 降序 → 取消排序之间循环。
    public CourseSortOrder Toggle(CourseColumn column) =>
        Column != column ? new(column) : !Descending ? this with { Descending = true } : new();
}

/// 课程目录的筛选条件;排序由列头决定。
public sealed record CourseFilter
{
    public const string AllCategories = "全部";

    public string Query { get; init; } = "";
    public string Category { get; init; } = AllCategories;
    public bool OnlyOpen { get; init; }
    public bool OnlyUnassigned { get; init; }

    public bool IsActive => Category != AllCategories || OnlyOpen || OnlyUnassigned;

    static readonly CompareInfo ChinaCompare = CultureInfo.GetCultureInfo("zh-CN").CompareInfo;

    public List<CourseRow> Apply(IEnumerable<CourseRow> courses, CourseSortOrder? sort = null)
    {
        var needle = Query.Trim();
        var matches = needle.Length == 0 && !IsActive
            ? courses
            : courses.Where(course =>
                (Category == AllCategories || course.Category == Category)
                && (!OnlyOpen || course.Availability == Availability.Open)
                && (!OnlyUnassigned || course.Group is null)
                && (needle.Length == 0 || course.SearchText.Contains(needle, StringComparison.OrdinalIgnoreCase)));
        return Sorted(matches, sort ?? new CourseSortOrder());
    }

    public static List<CourseRow> Sorted(IEnumerable<CourseRow> courses, CourseSortOrder sort)
    {
        if (sort.Column is not { } column) return [.. courses];
        var text = Comparer<string>.Create(CompareText);
        // OrderBy 是稳定排序,相同键保持目录顺序。
        IOrderedEnumerable<CourseRow> ordered = column switch
        {
            CourseColumn.Title => Order(courses, c => c.Title, text, sort.Descending),
            CourseColumn.Teachers => Order(courses, c => c.Teachers, text, sort.Descending),
            CourseColumn.Schedule => Order(courses, c => c.FirstSchedule, text, sort.Descending),
            CourseColumn.Kch => Order(courses, c => c.Kch ?? "", text, sort.Descending),
            CourseColumn.Group => Order(courses, c => c.Group ?? "", text, sort.Descending),
            CourseColumn.Seats => Order(courses, c => c.SortRemainingSeats, Comparer<int>.Default, sort.Descending),
            CourseColumn.Status => Order(courses, c => c.SortStatus, Comparer<int>.Default, sort.Descending),
            _ => Order(courses, c => c.Rating.SortScore ?? -1, Comparer<double>.Default, sort.Descending),
        };
        return [.. ordered];
    }

    static IOrderedEnumerable<CourseRow> Order<TKey>(IEnumerable<CourseRow> rows, Func<CourseRow, TKey> key, IComparer<TKey> comparer, bool descending) =>
        descending ? rows.OrderByDescending(key, comparer) : rows.OrderBy(key, comparer);

    static int CompareText(string? left, string? right) =>
        ChinaCompare.Compare(left, right, CompareOptions.IgnoreCase | CompareOptions.IgnoreWidth | CompareOptions.NumericOrdering);
}
