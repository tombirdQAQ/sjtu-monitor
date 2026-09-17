import JiaoWoXuanCore
import SwiftUI

struct SwapView: View {
    @Environment(AppStore.self) private var store
    @State private var confirmEnable = false

    var body: some View {
        if let snapshot = store.snapshot {
            VStack(spacing: 0) {
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
                    .tableStyle(.inset(alternatesRowBackgrounds: false))
                    .scrollContentBackground(.hidden)
                    .padding(6)
                    .glassCard(cornerRadius: 20)
                    .frame(minHeight: 140)
                }
                .padding(16)
                .frame(maxHeight: .infinity)

                VStack(alignment: .leading, spacing: 8) {
                    Text("换课记录").font(.headline).padding([.top, .horizontal], 16)
                    Table(snapshot.swapHistory.enumerated().map { IndexedSwapRow(id: $0.offset, element: $0.element) }) {
                        TableColumn("时间") { Text($0.element.timestamp ?? "-").monospacedDigit() }
                            .width(min: 130, ideal: 150)
                        TableColumn("模式") { Text($0.element.dryRun == true ? "通知" : "启用") }
                            .width(min: 40, ideal: 50)
                        TableColumn("方案") { Text($0.element.group ?? "-") }
                        TableColumn("课程") { Text($0.element.kcmc ?? AppStore.shortId($0.element.target)) }
                        TableColumn("结果") { row in
                            StatusBadge(text: row.element.ok == true ? "成功" : (row.element.status ?? "失败"),
                                        tone: row.element.ok == true ? .success : .danger)
                        }
                        .width(min: 60, ideal: 110)
                    }
                    .tableStyle(.inset(alternatesRowBackgrounds: false))
                    .scrollContentBackground(.hidden)
                    .padding(6)
                    .glassCard(cornerRadius: 20)
                    .padding([.horizontal, .bottom], 16)
                    .overlay {
                        if snapshot.swapHistory.isEmpty {
                            EmptyHint(title: "暂无换课记录", symbol: "clock.arrow.circlepath")
                        }
                    }
                }
                .frame(maxHeight: .infinity)
            }
            .background { AmbientBackground() }
            .confirmationDialog("启用自动换课？", isPresented: $confirmEnable) {
                Button("启用", role: .destructive) {
                    Task { await store.setAutoSwap(enabled: true, dryRun: false) }
                }
            } message: {
                Text("启用后监控会真正执行退课和选课。换课只会向更高优先级升级，不会降级；设置在重启监控后生效。")
            }
        }
    }

    private func modeSwitch(_ snapshot: Snapshot) -> some View {
        HStack(spacing: 16) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("自动换课").font(.headline)
                    Text(modeDescription(snapshot.metrics.autoSwap))
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
                    Text(AutoSwapState.off.label).tag(AutoSwapState.off)
                    Text(AutoSwapState.dryRun.label).tag(AutoSwapState.dryRun)
                    Text(AutoSwapState.enabled.label).tag(AutoSwapState.enabled)
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .fixedSize()
                .disabled(store.busy)
        }
        .padding(16)
        .glassCard(cornerRadius: 20, tint: snapshot.metrics.autoSwap == .enabled ? .red.opacity(0.15) : nil)
    }
}

private func modeDescription(_ mode: AutoSwapState) -> String {
    switch mode {
    case .off: "不处理换课，只记录余量变化。时间冲突的课程不会被选择。"
    case .dryRun: "发现可以换入的更高优先级课程时只发通知，不实际退选或选课。"
    case .enabled: "发现更高优先级课程有空位时自动退旧选新，只升级不降级。"
    }
}

private struct IndexedSwapRow: Identifiable {
    let id: Int
    let element: SwapHistoryRow
}
