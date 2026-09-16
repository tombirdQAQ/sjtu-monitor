import JiaoWoXuanCore
import SwiftUI

struct OverviewView: View {
    @Environment(AppStore.self) private var store

    var body: some View {
        if let snapshot = store.snapshot {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    header(snapshot)
                    MonitorCard(snapshot: snapshot)
                    metrics(snapshot.metrics)
                    HStack(alignment: .top, spacing: 16) {
                        profile(snapshot)
                        groupStatus(snapshot)
                    }
                }
                .padding(24)
                .frame(maxWidth: 1100, alignment: .leading)
                .frame(maxWidth: .infinity)
            }
        }
    }

    private func header(_ snapshot: Snapshot) -> some View {
        HStack(alignment: .firstTextBaseline) {
            VStack(alignment: .leading, spacing: 4) {
                Text(userValue(snapshot.user.name))
                    .font(.largeTitle.weight(.semibold))
                Text("\(snapshot.user.term) · \(userValue(snapshot.user.major))")
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Text("更新于 \(snapshot.generatedAt)")
                .font(.caption)
                .foregroundStyle(.tertiary)
        }
    }

    private func metrics(_ metrics: Metrics) -> some View {
        LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 12), count: 6), spacing: 12) {
            MetricTile(title: "查询课程", value: "\(metrics.queries)")
            MetricTile(title: "方案组", value: "\(metrics.groups)")
            MetricTile(title: "快照教学班", value: "\(metrics.snapshot)")
            MetricTile(title: "当前目标", value: "\(metrics.watched)")
            MetricTile(title: "目录空位", value: "\(metrics.openCourses)")
            MetricTile(title: "自动换课", value: metrics.autoSwap.label, tone: metrics.autoSwap.tone)
        }
    }

    private func profile(_ snapshot: Snapshot) -> some View {
        GroupBox {
            Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 8) {
                infoRow("姓名", userValue(snapshot.user.name))
                infoRow("学号", userValue(snapshot.user.studentId))
                infoRow("班级", userValue(snapshot.user.className))
                infoRow("专业", userValue(snapshot.user.major))
                infoRow("学期", snapshot.user.term)
                infoRow("目录更新", snapshot.user.catalogFetchedAt ?? "-")
                infoRow("已选同步", snapshot.choosedAt ?? "-")
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(6)
        } label: {
            Label("当前用户", systemImage: "person.crop.circle")
        }
    }

    private func infoRow(_ label: String, _ value: String) -> some View {
        GridRow {
            Text(label).foregroundStyle(.secondary)
            Text(value).textSelection(.enabled)
        }
    }

    private func groupStatus(_ snapshot: Snapshot) -> some View {
        GroupBox {
            if snapshot.groups.isEmpty {
                Text("尚未创建选课方案")
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, minHeight: 80)
            } else {
                VStack(spacing: 0) {
                    ForEach(snapshot.groups) { group in
                        Button {
                            store.selectedGroup = group.name
                            store.page = .courses
                        } label: {
                            HStack {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(group.name).font(.body.weight(.medium))
                                    Text("\(group.heldLabel) · 监控 \(group.watchedCount)")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                        .lineLimit(1)
                                }
                                Spacer()
                                if group.conflictCount > 0 {
                                    StatusBadge(text: "冲突 \(group.conflictCount)", tone: .danger)
                                }
                                if group.fatal { StatusBadge(text: "暂停", tone: .danger) }
                                Image(systemName: "chevron.right").foregroundStyle(.tertiary)
                            }
                            .padding(.vertical, 8)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        if group.id != snapshot.groups.last?.id { Divider() }
                    }
                }
                .padding(.horizontal, 6)
            }
        } label: {
            Label("方案状态", systemImage: "list.number")
        }
    }
}

private struct MetricTile: View {
    let title: String
    let value: String
    var tone: Tone = .neutral

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            Text(value)
                .font(.title2.weight(.semibold).monospacedDigit())
                .foregroundStyle(tone == .neutral ? AnyShapeStyle(.primary) : AnyShapeStyle(tone.color))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 10))
    }
}

private struct MonitorCard: View {
    @Environment(AppStore.self) private var store
    let snapshot: Snapshot

    var body: some View {
        let monitor = store.monitorRunning
        let once = store.running.contains("once")
        GroupBox {
            HStack(spacing: 16) {
                Image(systemName: monitor ? "dot.radiowaves.left.and.right" : "waveform.path.ecg")
                    .font(.system(size: 26, weight: .medium))
                    .foregroundStyle(monitor ? Color.green : (once ? Color.accentColor : Color.secondary))
                    .symbolEffect(.variableColor.iterative, isActive: monitor)
                    .frame(width: 44)
                VStack(alignment: .leading, spacing: 3) {
                    Text(monitor ? "持续监控中" : once ? "单次检查中" : "未运行")
                        .font(.title3.weight(.semibold))
                    Text(monitor ? "正在按配置轮询课程余量" : once ? "正在执行一次本地监控流程" : "可以启动单次检查或持续监控")
                        .foregroundStyle(.secondary)
                }
                Spacer()
                LabeledContent("轮询间隔", value: snapshot.metrics.interval)
                    .fixedSize(horizontal: true, vertical: false)
                Divider().frame(height: 28)
                HStack(spacing: 6) {
                    Text("自动换课").foregroundStyle(.secondary)
                    StatusBadge(text: snapshot.metrics.autoSwap.label, tone: snapshot.metrics.autoSwap.tone)
                }
                Divider().frame(height: 28)
                Button(once ? "检查中…" : "单次检查") { store.run("once") }
                    .disabled(once)
                if monitor {
                    Button("停止监控", role: .destructive) { store.stop("monitor") }
                } else {
                    Button("开始持续监控") { store.run("monitor") }
                        .keyboardShortcut(.defaultAction)
                }
            }
            .padding(8)
        }
    }
}
