using System.Globalization;

namespace JiaoWoXuan.Core;

public enum CourseSort { Catalog, Name, Rating }

/// 课程目录的筛选条件。纯展示逻辑,与业务规则无关。
public sealed record CourseFilter
{
    public const string AllCategories = "全部";

    public string Query { get; init; } = "";
    public string Category { get; init; } = AllCategories;
    public bool OnlyOpen { get; init; }
    public bool OnlyUnassigned { get; init; }
    public CourseSort Sort { get; init; } = CourseSort.Catalog;

    static readonly CompareInfo ChinaCompare = CultureInfo.GetCultureInfo("zh-CN").CompareInfo;

    public List<CourseRow> Apply(IEnumerable<CourseRow> courses)
    {
        var needle = Query.Trim();
        var matches = courses.Where(course =>
            (Category == AllCategories || course.Category == Category)
            && (!OnlyOpen || course.Availability == Availability.Open)
            && (!OnlyUnassigned || course.Group is null)
            && (needle.Length == 0 || course.SearchText.Contains(needle, StringComparison.OrdinalIgnoreCase)));
        return Sorted(matches, Sort);
    }

    public static List<CourseRow> Sorted(IEnumerable<CourseRow> courses, CourseSort sort)
    {
        var list = courses.ToList();
        if (sort == CourseSort.Catalog) return list;
        // List.Sort 不稳定,用 OrderBy 保证同分同名时顺序确定。
        IEnumerable<CourseRow> ordered = sort == CourseSort.Rating
            ? list.OrderBy(c => c.Rating.SortScore is null).ThenByDescending(c => c.Rating.SortScore ?? 0)
                .ThenBy(c => c.Title, Comparer<string>.Create(CompareTitles))
            : list.OrderBy(c => c.Title, Comparer<string>.Create(CompareTitles));
        return [.. ordered is IOrderedEnumerable<CourseRow> o ? o.ThenBy(c => c.JxbId, StringComparer.Ordinal) : ordered];
    }

    static int CompareTitles(string? left, string? right) =>
        ChinaCompare.Compare(left, right, CompareOptions.IgnoreCase | CompareOptions.IgnoreWidth | CompareOptions.NumericOrdering);
}
