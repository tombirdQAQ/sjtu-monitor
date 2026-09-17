import JiaoWoXuanCore
import SwiftUI

struct RootView: View {
    @Environment(AppStore.self) private var store

    var body: some View {
        @Bindable var store = store
        Group {
            switch store.phase {
            case .starting:
                ProgressView("正在启动后端服务…")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            case .failed(let message):
                ContentUnavailableView {
                    Label("后端服务不可用", systemImage: "exclamationmark.triangle")
                } description: {
                    Text(message).textSelection(.enabled)
                } actions: {
                    Button("重新启动后端") { store.restartBackend() }
                }
            case .ready:
                if store.snapshot == nil {
                    ProgressView("正在读取本地状态…")
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else if store.needsOnboarding {
                    OnboardingView()
                } else {
                    Workbench()
                }
            }
        }
        .alert(
            store.notice?.title ?? "",
            isPresented: Binding(get: { store.notice != nil }, set: { if !$0 { store.notice = nil } }),
            presenting: store.notice
        ) { _ in
            Button("好") { store.notice = nil }
        } message: { notice in
            Text(notice.message)
        }
    }
}

private struct Workbench: View {
    @Environment(AppStore.self) private var store
    /// 边栏选中项用本地 @State + NavigationLink(value:) 驱动(SwiftUI 边栏的标准写法),
    /// 再与 store.page 双向同步:菜单快捷键、总览里的跳转都会改 store.page。
    @State private var selection: Page? = .overview

    var body: some View {
        NavigationSplitView {
            List(selection: $selection) {
                Section("工作台") {
                    ForEach([Page.overview, .courses, .swap]) { page in
                        // 不用 .badge:在 macOS 26+ 的边栏里它会让 List 的选中完全失效(点击无反应)。
                        NavigationLink(value: page) {
                            SidebarRow(page: page, dirty: page == .courses && store.groupsDirty)
                        }
                    }
                }
                Section("数据") {
                    ForEach([Page.snapshot, .logs]) { page in
                        NavigationLink(value: page) {
                            SidebarRow(page: page, dirty: false)
                        }
                    }
                }
            }
            .navigationSplitViewColumnWidth(min: 190, ideal: 220)
            .safeAreaInset(edge: .bottom) { SidebarMonitorStatus() }
        } detail: {
            detail
                .navigationTitle(store.page.title)
                .navigationSubtitle(subtitle)
                .toolbar { MonitorToolbar() }
        }
        .onAppear { selection = store.page }
        .onChange(of: selection) { _, value in
            if let value, value != store.page { store.page = value }
        }
        .onChange(of: store.page) { _, value in
            if selection != value { selection = value }
        }
    }

    @ViewBuilder
    private var detail: some View {
        switch store.page {
        case .overview: OverviewView()
        case .courses: CoursesView()
        case .swap: SwapView()
        case .snapshot: SnapshotView()
        case .logs: LogsView()
        }
    }

    private var subtitle: String {
        if store.groupsDirty { return "方案有未保存的修改" }
        return store.status
    }
}

/// 边栏行:悬停时显示浅色高亮(系统边栏默认没有悬停反馈)。
private struct SidebarRow: View {
    let page: Page
    let dirty: Bool
    @State private var hovering = false

    var body: some View {
        HStack {
            Label(page.title, systemImage: page.symbol)
            Spacer(minLength: 0)
            if dirty {
                Circle()
                    .fill(.orange)
                    .frame(width: 7, height: 7)
                    .help("方案有未保存的修改")
            }
        }
        .contentShape(Rectangle())
        .background {
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(Color.primary.opacity(hovering ? 0.08 : 0))
                .padding(.horizontal, -8)
                .padding(.vertical, -4)
        }
        .animation(.easeOut(duration: 0.12), value: hovering)
        .onHover { hovering = $0 }
    }
}

private struct SidebarMonitorStatus: View {
    @Environment(AppStore.self) private var store

    var body: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(store.monitorRunning ? Color.green : (store.running.isEmpty ? Color.secondary.opacity(0.5) : Color.accentColor))
                .frame(width: 8, height: 8)
            VStack(alignment: .leading, spacing: 1) {
                Text(store.monitorRunning ? "持续监控中" : store.running.contains("once") ? "单次检查中" : "监控未运行")
                    .font(.callout.weight(.medium))
                if let term = store.snapshot?.user.term {
                    Text(term).font(.caption).foregroundStyle(.secondary)
                }
            }
            Spacer()
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .glassCard(cornerRadius: 14, tint: store.monitorRunning ? .green.opacity(0.18) : nil)
        .padding(.horizontal, 10)
        .padding(.bottom, 10)
    }
}

struct MonitorToolbar: ToolbarContent {
    @Environment(AppStore.self) private var store

    var body: some ToolbarContent {
        ToolbarItemGroup(placement: .primaryAction) {
            let busyTasks = store.running.subtracting(["monitor"]).sorted()
            if !busyTasks.isEmpty {
                ProgressView()
                    .controlSize(.small)
                    .help("正在运行：\(busyTasks.joined(separator: "、"))")
            }
            Button {
                Task { await store.refresh() }
            } label: {
                Label("刷新", systemImage: "arrow.clockwise")
            }
            .help("刷新本地状态 (⌘R)")
            .disabled(store.busy)

            Button {
                store.run("once")
            } label: {
                Label("单次检查", systemImage: "play")
            }
            .help("执行一次监控流程")
            .disabled(store.running.contains("once"))

            if store.monitorRunning {
                Button {
                    store.stop("monitor")
                } label: {
                    Label("停止监控", systemImage: "stop.fill")
                }
                .help("停止持续监控")
            } else {
                Button {
                    store.run("monitor")
                } label: {
                    Label("开始监控", systemImage: "dot.radiowaves.left.and.right")
                }
                .help("开始持续监控")
            }
        }
    }
}
