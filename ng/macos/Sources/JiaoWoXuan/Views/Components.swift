import JiaoWoXuanCore
import SwiftUI

enum Tone {
    case neutral, accent, success, danger, warning

    var color: Color {
        switch self {
        case .neutral: .secondary
        case .accent: .accentColor
        case .success: .green
        case .danger: .red
        case .warning: .orange
        }
    }
}

/// 紧凑的状态标签,样式接近 Finder 标签/邮件里的小胶囊。
struct StatusBadge: View {
    let text: String
    var tone: Tone = .neutral

    var body: some View {
        Text(text)
            .font(.caption.weight(.medium))
            .lineLimit(1)
            .padding(.horizontal, 6)
            .padding(.vertical, 1.5)
            .foregroundStyle(tone == .neutral ? AnyShapeStyle(.secondary) : AnyShapeStyle(tone.color))
            .background(tone.color.opacity(tone == .neutral ? 0.12 : 0.14), in: Capsule())
    }
}

extension CourseRow {
    var statusText: String { chosen ? "已选" : availabilityText }
    var statusTone: Tone { chosen ? .accent : (availability == .open ? .success : .neutral) }
}

extension AutoSwapState {
    var tone: Tone {
        switch self {
        case .enabled: .danger
        case .dryRun: .accent
        case .off: .neutral
        }
    }
}

extension LogLevel {
    var label: String {
        switch self {
        case .info: "信息"
        case .warn: "警告"
        case .error: "错误"
        case .debug: "调试"
        }
    }

    var tone: Tone {
        switch self {
        case .info: .accent
        case .warn: .warning
        case .error: .danger
        case .debug: .neutral
        }
    }
}

/// 未同步的用户字段显示为"未同步",而不是假定抓取成功。
func userValue(_ value: String?) -> String {
    let text = (value ?? "").trimmingCharacters(in: .whitespaces)
    return text.isEmpty || text == "-" ? "未同步" : text
}

struct EmptyHint: View {
    let title: String
    let symbol: String
    var message: String? = nil

    var body: some View {
        ContentUnavailableView {
            Label(title, systemImage: symbol)
        } description: {
            if let message { Text(message) }
        }
    }
}
