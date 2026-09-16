import JiaoWoXuanCore
import SwiftUI

struct SnapshotView: View {
    @Environment(AppStore.self) private var store

    var body: some View {
        @Bindable var store = store
        let rows = store.stateRows
        Table(rows) {
            TableColumn("") { row in
                if row.watched {
                    Image(systemName: "eye").foregroundStyle(Color.accentColor).help("当前监控目标")
                }
            }
            .width(22)
            TableColumn("方案") { Text($0.group ?? "-").foregroundStyle(.secondary) }
                .width(min: 60, ideal: 90)
            TableColumn("课程") { row in
                VStack(alignment: .leading, spacing: 1) {
                    Text(row.title)
                    Text(row.summary).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                }
            }
            .width(min: 240, ideal: 420)
            TableColumn("已选 / 容量") { Text($0.seatText).monospacedDigit() }
                .width(min: 70, ideal: 90)
            TableColumn("状态") { row in
                StatusBadge(
                    text: row.open == true ? "有空位" : row.open == false ? "已满" : "未知",
                    tone: row.open == true ? .success : .neutral
                )
            }
            .width(min: 50, ideal: 64)
        }
        .tableStyle(.inset(alternatesRowBackgrounds: true))
        .overlay {
            if rows.isEmpty {
                EmptyHint(title: "没有快照数据", symbol: "list.bullet.clipboard", message: "运行一次监控后这里会显示各教学班的余量")
            }
        }
        .toolbar {
            ToolbarItem {
                Picker("范围", selection: $store.stateFilter) {
                    ForEach(StateFilter.allCases) { Text($0.label).tag($0) }
                }
                .pickerStyle(.segmented)
            }
        }
    }
}
