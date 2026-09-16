import JiaoWoXuanCore
import SwiftUI

struct SwapView: View {
    @Environment(AppStore.self) private var store
    @State private var confirmEnable = false

    var body: some View {
        if let snapshot = store.snapshot {
            VSplitView {
                VStack(alignment: .leading, spacing: 14) {
                    modeSwitch(snapshot)
                    Text("方案执行状态").font(.headline)
                    Table(snapshot.groups) {
                        TableColumn("方案", value: \.name)
                        TableColumn("类型") { Text($0.isPe ? "体育" : "普通") }
                            .width(min: 40, ideal: 50)
                        TableColumn("当前持有", value: \.heldLabel)
                        TableColumn("监控目标") { Text("\($0.watchedCount)").monospacedDigit() }
                            .width(min: 50, ideal: 64)
                        TableColumn("完成") { group in
                            Text("\(snapshot.swapState.completed.filter(group.priority.contains).count)").monospacedDigit()
                        }
                        .width(min: 40, ideal: 50)
                        TableColumn("失败") { group in
                            if group.fatal {
                                StatusBadge(text: "方案暂停", tone: .danger)
                            } else {
                                Text("\(snapshot.swapState.fatal.filter(group.priority.contains).count)").monospacedDigit()
                            }
                        }
                        .width(min: 50, ideal: 70)
                    }
                    .tableStyle(.inset)
                    .frame(minHeight: 140)
                }
                .padding(16)
                .frame(minHeight: 260)

                VStack(alignment: .leading, spacing: 8) {
                    Text("换课记录").font(.headline).padding([.top, .horizontal], 16)
                    Table(snapshot.swapHistory.enumerated().map { IndexedSwapRow(id: $0.offset, element: $0.element) }) {
                        TableColumn("时间") { Text($0.element.timestamp ?? "-").monospacedDigit() }
                            .width(min: 130, ideal: 150)
                        TableColumn("模式") { Text($0.element.dryRun == true ? "演练" : "真实") }
                            .width(min: 40, ideal: 50)
                        TableColumn("方案") { Text($0.element.group ?? "-") }
                        TableColumn("课程") { Text($0.element.kcmc ?? AppStore.shortId($0.element.target)) }
                        TableColumn("结果") { row in
                            StatusBadge(text: row.element.ok == true ? "成功" : (row.element.status ?? "失败"),
                                        tone: row.element.ok == true ? .success : .danger)
                        }
                        .width(min: 60, ideal: 110)
                    }
                    .tableStyle(.inset)
                    .overlay {
                        if snapshot.swapHistory.isEmpty {
                            EmptyHint(title: "暂无换课记录", symbol: "clock.arrow.circlepath")
                        }
                    }
                }
                .frame(minHeight: 160)
            }
            .confirmationDialog("启用真实自动换课？", isPresented: $confirmEnable) {
                Button("启用", role: .destructive) {
                    Task { await store.setAutoSwap(enabled: true, dryRun: false) }
                }
            } message: {
                Text("真实自动换课会执行退课和选课。换课只会向更高优先级升级，不会降级；设置在重启监控后生效。")
            }
        }
    }

    private func modeSwitch(_ snapshot: Snapshot) -> some View {
        GroupBox {
            HStack(spacing: 16) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("自动换课").font(.headline)
                    Text("监控发现更高优先级课程有空位时自动退旧选新；时间冲突的课程不会被选择。")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Picker("自动换课", selection: Binding(
                    get: { snapshot.metrics.autoSwap },
                    set: { value in
                        switch value {
                        case .off: Task { await store.setAutoSwap(enabled: false, dryRun: false) }
                        case .dryRun: Task { await store.setAutoSwap(enabled: true, dryRun: true) }
                        case .enabled: confirmEnable = true
                        }
                    }
                )) {
                    Text("关闭").tag(AutoSwapState.off)
                    if !store.releaseMode { Text("演练").tag(AutoSwapState.dryRun) }
                    Text("真实启用").tag(AutoSwapState.enabled)
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .fixedSize()
                .disabled(store.busy)
            }
            .padding(6)
        }
    }
}

private struct IndexedSwapRow: Identifiable {
    let id: Int
    let element: SwapHistoryRow
}
