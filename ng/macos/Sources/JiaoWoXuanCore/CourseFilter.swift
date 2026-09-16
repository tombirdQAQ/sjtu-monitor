import Foundation

public enum CourseSort: String, CaseIterable, Identifiable, Sendable {
    case catalog, name, rating
    public var id: String { rawValue }
    public var label: String {
        switch self {
        case .catalog: "目录顺序"
        case .name: "课程名称"
        case .rating: "评分从高到低"
        }
    }
}

/// 课程目录的筛选条件。纯展示逻辑:与业务规则无关,各客户端各自实现即可。
public struct CourseFilter: Equatable, Sendable {
    public static let allCategories = "全部"

    public var query = ""
    public var category = CourseFilter.allCategories
    public var onlyOpen = false
    public var onlyUnassigned = false
    public var sort: CourseSort = .catalog

    public init() {}

    public func apply(to courses: [CourseRow]) -> [CourseRow] {
        let needle = query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let matches = courses.filter { course in
            if category != Self.allCategories && course.category != category { return false }
            if onlyOpen && course.availability != .open { return false }
            if onlyUnassigned && course.group != nil { return false }
            if !needle.isEmpty && !course.searchText.lowercased().contains(needle) { return false }
            return true
        }
        return Self.sorted(matches, by: sort)
    }

    private static let chinaLocale = Locale(identifier: "zh_CN")

    public static func sorted(_ courses: [CourseRow], by sort: CourseSort) -> [CourseRow] {
        guard sort != .catalog else { return courses }
        return courses.sorted { left, right in
            if sort == .rating, left.rating.sortScore != right.rating.sortScore {
                switch (left.rating.sortScore, right.rating.sortScore) {
                case (nil, _): return false
                case (_, nil): return true
                case let (l?, r?): return l > r
                }
            }
            let order = left.title.compare(
                right.title,
                options: [.caseInsensitive, .numeric, .widthInsensitive],
                range: nil,
                locale: chinaLocale
            )
            if order != .orderedSame { return order == .orderedAscending }
            return left.jxbId < right.jxbId
        }
    }
}
