import JiaoWoXuanCore
import SwiftUI

struct LogsView: View {
    @Environment(AppStore.self) private var store
    @State private var followTail = true

    var body: some View {
        @Bindable var store = store
        let entries = store.logs.entries
        ScrollViewReader { proxy in
            List {
                ForEach(Array(entries.enumerated()), id: \.offset) { index, entry in
                    LogRow(entry: entry).id(index)
                }
            }
            .listStyle(.plain)
            .font(.system(.callout, design: .monospaced))
            .textSelection(.enabled)
            .overlay {
                if entries.isEmpty { EmptyHint(title: "暂无符合条件的日志", symbol: "text.alignleft") }
            }
            .onChange(of: entries.count) { _, count in
                guard followTail, count > 0 else { return }
                proxy.scrollTo(count - 1, anchor: .bottom)
            }
            .onAppear {
                store.reloadLogs()
            }
        }
        .searchable(text: $store.logQuery, placement: .toolbar, prompt: "筛选日志")
        .toolbar {
            ToolbarItem {
                Picker("级别", selection: $store.logLevel) {
                    Text("全部 \(store.logs.counts.all)").tag(LogLevel?.none)
                    ForEach(LogLevel.allCases) { level in
                        Text("\(level.label) \(store.logs.counts.count(for: level))").tag(LogLevel?.some(level))
                    }
                }
                .pickerStyle(.segmented)
            }
            ToolbarItem {
                Toggle(isOn: $followTail) {
                    Label("跟随最新", systemImage: "arrow.down.to.line")
                }
                .help("有新日志时自动滚动到底部")
            }
        }
    }
}

private struct LogRow: View {
    let entry: LogEntry

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Text(entry.time.isEmpty ? "--:--:--" : entry.time)
                .foregroundStyle(.secondary)
            Text(entry.level.label)
                .font(.caption.weight(.semibold))
                .foregroundStyle(entry.level.tone.color)
                .frame(width: 30, alignment: .leading)
            Text(entry.source)
                .foregroundStyle(.secondary)
                .frame(width: 90, alignment: .leading)
                .lineLimit(1)
            Text(entry.message)
                .foregroundStyle(entry.level == .error ? AnyShapeStyle(Color.red) : AnyShapeStyle(.primary))
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .listRowSeparator(.hidden)
    }
}
