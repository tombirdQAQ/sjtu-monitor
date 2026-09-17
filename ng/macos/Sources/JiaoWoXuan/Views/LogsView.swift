import JiaoWoXuanCore
import SwiftUI

struct LogsView: View {
    @Environment(AppStore.self) private var store
    @State private var followTail = true

    var body: some View {
        @Bindable var store = store
        let entries = store.logs.entries
        VStack(spacing: 14) {
            LevelSummary()
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(spacing: 2) {
                        ForEach(Array(entries.enumerated()), id: \.offset) { index, entry in
                            LogRow(entry: entry).id(index)
                        }
                    }
                    .padding(8)
                }
                .scrollContentBackground(.hidden)
                .overlay {
                    if entries.isEmpty {
                        EmptyHint(
                            title: store.logQuery.isEmpty && store.logLevel == nil ? "暂无日志" : "没有符合条件的日志",
                            symbol: "text.alignleft",
                            message: "监控、抓取的输出与选课变动都会出现在这里"
                        )
                    }
                }
                .onChange(of: entries.count) { _, count in
                    guard followTail, count > 0 else { return }
                    withAnimation(.easeOut(duration: 0.2)) { proxy.scrollTo(count - 1, anchor: .bottom) }
                }
                .onAppear {
                    store.reloadLogs()
                    if !entries.isEmpty { proxy.scrollTo(entries.count - 1, anchor: .bottom) }
                }
            }
            .glassCard(cornerRadius: 22)
        }
        .padding(16)
        .background { AmbientBackground() }
        .searchable(text: $store.logQuery, placement: .toolbar, prompt: "筛选日志内容或来源")
        .toolbar {
            ToolbarItem {
                Toggle(isOn: $followTail) {
                    Label("跟随最新", systemImage: "arrow.down.to.line")
                }
                .help("有新日志时自动滚动到底部")
            }
        }
    }
}

/// 顶部级别概览:可点击的玻璃统计卡片,兼作级别筛选。
private struct LevelSummary: View {
    @Environment(AppStore.self) private var store

    var body: some View {
        let counts = store.logs.counts
        GlassGroup(spacing: 10) {
            HStack(spacing: 10) {
                LevelChip(title: "全部", symbol: "tray.full", count: counts.all, tint: .accentColor,
                          selected: store.logLevel == nil) { store.logLevel = nil }
                ForEach(LogLevel.allCases) { level in
                    LevelChip(title: level.label, symbol: level.symbol, count: counts.count(for: level),
                              tint: level.tone.color, selected: store.logLevel == level) {
                        store.logLevel = store.logLevel == level ? nil : level
                    }
                }
            }
        }
    }
}

private struct LevelChip: View {
    let title: String
    let symbol: String
    let count: Int
    let tint: Color
    let selected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 10) {
                Image(systemName: symbol)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(selected ? AnyShapeStyle(.white) : AnyShapeStyle(tint))
                    .frame(width: 30, height: 30)
                    .background(Circle().fill(selected ? tint : tint.opacity(0.15)))
                VStack(alignment: .leading, spacing: 0) {
                    Text("\(count)")
                        .font(.system(size: 18, weight: .semibold, design: .rounded).monospacedDigit())
                    Text(title).font(.caption).foregroundStyle(.secondary)
                }
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 9)
            .frame(maxWidth: .infinity)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .glassCard(cornerRadius: 16, tint: selected ? tint.opacity(0.22) : nil, interactive: true)
    }
}

private struct LogRow: View {
    let entry: LogEntry
    @State private var hovering = false

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Text(entry.time.isEmpty ? "--:--:--" : entry.time)
                .font(.system(.caption, design: .monospaced))
                .foregroundStyle(.secondary)
                .frame(width: 58, alignment: .leading)
            Label(entry.level.label, systemImage: entry.level.symbol)
                .labelStyle(.titleAndIcon)
                .font(.caption.weight(.semibold))
                .foregroundStyle(entry.level.tone.color)
                .padding(.horizontal, 7)
                .padding(.vertical, 2)
                .background(Capsule().fill(entry.level.tone.color.opacity(0.12)))
                .frame(width: 64, alignment: .leading)
            Text(entry.source)
                .font(.caption.weight(.medium))
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .padding(.horizontal, 7)
                .padding(.vertical, 2)
                .background(Capsule().strokeBorder(.separator))
                .frame(width: 104, alignment: .leading)
            Text(entry.message)
                .font(.callout)
                .foregroundStyle(entry.level == .error ? AnyShapeStyle(Color.red) : AnyShapeStyle(.primary))
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 7)
        .background {
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(rowTint)
        }
        .onHover { hovering = $0 }
    }

    private var rowTint: Color {
        switch entry.level {
        case .error: return Color.red.opacity(hovering ? 0.14 : 0.08)
        case .warn: return Color.orange.opacity(hovering ? 0.12 : 0.05)
        default: return Color.primary.opacity(hovering ? 0.06 : 0)
        }
    }
}

extension LogLevel {
    var symbol: String {
        switch self {
        case .info: "info.circle.fill"
        case .warn: "exclamationmark.triangle.fill"
        case .error: "xmark.octagon.fill"
        case .debug: "ladybug.fill"
        }
    }
}
