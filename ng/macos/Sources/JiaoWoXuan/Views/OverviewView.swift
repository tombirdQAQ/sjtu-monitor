import JiaoWoXuanCore
import SwiftUI

struct OverviewView: View {
    @Environment(AppStore.self) private var store

    var body: some View {
        if let snapshot = store.snapshot {
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    header(snapshot)
                    MonitorCard(snapshot: snapshot)
                    metrics(snapshot.metrics)
                    HStack(alignment: .top, spacing: 18) {
                        profile(snapshot)
                        groupStatus(snapshot)
                    }
                }
                .padding(.horizontal, 28)
                .padding(.vertical, 24)
                .frame(maxWidth: 1120, alignment: .leading)
                .frame(maxWidth: .infinity)
            }
            .background { AmbientBackground() }
        }
    }

    private func header(_ snapshot: Snapshot) -> some View {
        HStack(alignment: .bottom) {
            VStack(alignment: .leading, spacing: 6) {
                Text(snapshot.user.term)
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(.secondary)
                Text(userValue(snapshot.user.name))
                    .font(.system(size: 34, weight: .bold, design: .rounded))
                Text(userValue(snapshot.user.major))
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Label("更新于 \(snapshot.generatedAt.replacingOccurrences(of: "T", with: " "))", systemImage: "clock")
                .font(.caption)
                .foregroundStyle(.secondary)
                .padding(.horizontal, 12)
                .padding(.vertical, 6)
                .glassCapsule()
        }
    }

    private func metrics(_ metrics: Metrics) -> some View {
        GlassGroup(spacing: 14) {
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 14), count: 6), spacing: 14) {
                MetricTile(title: "查询课程", value: "\(metrics.queries)", symbol: "magnifyingglass")
                MetricTile(title: "方案组", value: "\(metrics.groups)", symbol: "list.number")
                MetricTile(title: "快照教学班", value: "\(metrics.snapshot)", symbol: "square.stack.3d.up")
                MetricTile(title: "当前目标", value: "\(metrics.watched)", symbol: "scope")
                MetricTile(title: "目录空位", value: "\(metrics.openCourses)", symbol: "chair")
                MetricTile(title: "自动换课", value: metrics.autoSwap.label, symbol: "arrow.triangle.swap",
                           tone: metrics.autoSwap.tone)
            }
        }
    }

    private func profile(_ snapshot: Snapshot) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            Label("当前用户", systemImage: "person.crop.circle").font(.headline)
            Grid(alignment: .leading, horizontalSpacing: 18, verticalSpacing: 9) {
                infoRow("姓名", userValue(snapshot.user.name))
                infoRow("学号", userValue(snapshot.user.studentId))
                infoRow("班级", userValue(snapshot.user.className))
                infoRow("专业", userValue(snapshot.user.major))
                infoRow("目录更新", snapshot.user.catalogFetchedAt ?? "-")
                infoRow("已选同步", snapshot.choosedAt ?? "-")
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(20)
        .glassCard(cornerRadius: 22)
    }

    private func infoRow(_ label: String, _ value: String) -> some View {
        GridRow {
            Text(label).foregroundStyle(.secondary)
            Text(value).textSelection(.enabled)
        }
    }

    private func groupStatus(_ snapshot: Snapshot) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("方案状态", systemImage: "list.number").font(.headline)
            if snapshot.groups.isEmpty {
                Text("尚未创建选课方案")
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, minHeight: 80)
            } else {
                GlassGroup(spacing: 8) {
                    VStack(spacing: 8) {
                        ForEach(snapshot.groups) { group in
                            Button {
                                store.selectedGroup = group.name
                                store.page = .courses
                            } label: {
                                HStack(spacing: 10) {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(group.name).font(.body.weight(.semibold))
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
                                    Image(systemName: "chevron.right")
                                        .font(.caption.weight(.semibold))
                                        .foregroundStyle(.tertiary)
                                }
                                .padding(.horizontal, 14)
                                .padding(.vertical, 10)
                                .contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                            .glassCard(cornerRadius: 14, interactive: true)
                        }
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(20)
        .glassCard(cornerRadius: 22)
    }
}

private struct MetricTile: View {
    let title: String
    let value: String
    let symbol: String
    var tone: Tone = .neutral

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Image(systemName: symbol)
                .font(.callout.weight(.semibold))
                .foregroundStyle(tone == .neutral ? AnyShapeStyle(.secondary) : AnyShapeStyle(tone.color))
            Text(value)
                .font(.system(size: 24, weight: .semibold, design: .rounded).monospacedDigit())
                .foregroundStyle(tone == .neutral ? AnyShapeStyle(.primary) : AnyShapeStyle(tone.color))
                .lineLimit(1)
                .minimumScaleFactor(0.7)
            Text(title).font(.caption).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .glassCard(cornerRadius: 18, tint: tone == .neutral ? nil : tone.color.opacity(0.25))
    }
}

private struct MonitorCard: View {
    @Environment(AppStore.self) private var store
    let snapshot: Snapshot

    var body: some View {
        let monitor = store.monitorRunning
        let once = store.running.contains("once")
        let tint: Color? = monitor ? .green.opacity(0.22) : nil
        HStack(spacing: 18) {
            Image(systemName: monitor ? "dot.radiowaves.left.and.right" : "waveform.path.ecg")
                .font(.system(size: 26, weight: .semibold))
                .foregroundStyle(monitor ? Color.green : (once ? Color.accentColor : Color.secondary))
                .symbolEffect(.variableColor.iterative, isActive: monitor)
                .frame(width: 56, height: 56)
                .glassCard(cornerRadius: 28)
            VStack(alignment: .leading, spacing: 4) {
                Text(monitor ? "持续监控中" : once ? "单次检查中" : "监控未运行")
                    .font(.title2.weight(.semibold))
                Text(monitor ? "正在按配置轮询课程余量" : once ? "正在执行一次本地监控流程" : "可以启动单次检查或持续监控")
                    .foregroundStyle(.secondary)
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 6) {
                HStack(spacing: 6) {
                    Text("轮询").foregroundStyle(.secondary)
                    Text(snapshot.metrics.interval).monospacedDigit()
                }
                HStack(spacing: 6) {
                    Text("自动换课").foregroundStyle(.secondary)
                    StatusBadge(text: snapshot.metrics.autoSwap.label, tone: snapshot.metrics.autoSwap.tone)
                }
            }
            .font(.callout)
            GlassGroup(spacing: 8) {
                HStack(spacing: 8) {
                    Button {
                        store.run("once")
                    } label: {
                        Label(once ? "检查中…" : "单次检查", systemImage: "play.fill")
                    }
                    .glassButton()
                    .disabled(once)
                    if monitor {
                        Button(role: .destructive) {
                            store.stop("monitor")
                        } label: {
                            Label("停止监控", systemImage: "stop.fill")
                        }
                        .glassButton()
                    } else {
                        Button {
                            store.run("monitor")
                        } label: {
                            Label("开始持续监控", systemImage: "dot.radiowaves.left.and.right")
                        }
                        .glassButton(prominent: true)
                    }
                }
                .controlSize(.large)
            }
        }
        .padding(20)
        .glassCard(cornerRadius: 26, tint: tint)
    }
}
