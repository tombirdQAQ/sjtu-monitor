import Foundation

/// 课程目录的筛选条件。排序由表格列头决定(见 CourseRow 的排序键),这里只负责筛选。
public struct CourseFilter: Equatable, Sendable {
    public static let allCategories = "全部"

    public var query = ""
    public var category = CourseFilter.allCategories
    public var onlyOpen = false
    public var onlyUnassigned = false

    public init() {}

    public var isActive: Bool {
        category != Self.allCategories || onlyOpen || onlyUnassigned
    }

    public func apply(to courses: [CourseRow]) -> [CourseRow] {
        let needle = query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !needle.isEmpty || isActive else { return courses }
        return courses.filter { course in
            if category != Self.allCategories && course.category != category { return false }
            if onlyOpen && course.availability != .open { return false }
            if onlyUnassigned && course.group != nil { return false }
            if !needle.isEmpty && !course.searchText.contains(needle) { return false }
            return true
        }
    }
}

// MARK: - 列头排序用的键(都是非可选类型,可直接用于 KeyPathComparator)

extension CourseRow {
    public var sortKch: String { kch ?? "" }
    public var sortGroup: String { group ?? "" }

    /// 剩余名额;无法解析时排在最后(升序)/最前(降序)。
    public var sortRemainingSeats: Int {
        let parts = seatText.split(separator: "/").map { Int($0.trimmingCharacters(in: .whitespaces)) }
        guard parts.count == 2, let selected = parts[0], let capacity = parts[1] else { return Int.min }
        return capacity - selected
    }

    /// 已选 < 有空位 < 已满 < 未知。
    public var sortStatus: Int {
        if chosen { return 0 }
        switch availability {
        case .open: return 1
        case .full: return 2
        case .unknown: return 3
        }
    }

    /// 只有 rated 参与分数排序;未评分记为 -1。
    public var sortRating: Double { rating.sortScore ?? -1 }
}
