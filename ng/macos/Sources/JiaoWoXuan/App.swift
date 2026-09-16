import AppKit
import JiaoWoXuanCore
import SwiftUI

enum Appearance: String, CaseIterable, Identifiable {
    case system, light, dark
    var id: String { rawValue }
    var label: String {
        switch self {
        case .system: "跟随系统"
        case .light: "浅色"
        case .dark: "深色"
        }
    }

    @MainActor
    func apply() {
        switch self {
        case .system: NSApp.appearance = nil
        case .light: NSApp.appearance = NSAppearance(named: .aqua)
        case .dark: NSApp.appearance = NSAppearance(named: .darkAqua)
        }
    }
}

@main
struct JiaoWoXuanApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @AppStorage("appearance") private var appearance: Appearance = .system

    private var store: AppStore { AppDelegate.store }

    var body: some Scene {
        Window("交我选", id: "main") {
            RootView()
                .environment(store)
                .frame(minWidth: 960, minHeight: 640)
                .onAppear { appearance.apply() }
                .onChange(of: appearance) { _, value in value.apply() }
        }
        .defaultSize(width: 1280, height: 820)
        .commands { AppCommands(store: store) }

        Settings {
            SettingsView()
                .environment(store)
        }

        MenuBarExtra {
            MenuBarContent()
                .environment(store)
        } label: {
            Image(systemName: store.monitorRunning ? "dot.radiowaves.left.and.right" : "graduationcap")
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    @MainActor static let store = AppStore()

    func applicationDidFinishLaunching(_ notification: Notification) {
        // `swift run` 启动的裸可执行文件默认是后台进程,需要显式变成普通应用才有 Dock 图标和菜单栏。
        if Bundle.main.bundleIdentifier == nil {
            NSApp.setActivationPolicy(.regular)
            NSApp.activate(ignoringOtherApps: true)
        }
        MainActor.assumeIsolated { Self.store.start() }
    }

    /// 关掉窗口后监控继续在菜单栏里运行。
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        MainActor.assumeIsolated {
            let store = Self.store
            var reasons: [String] = []
            if store.groupsDirty { reasons.append("选课方案还有未保存的修改，退出后将丢失。") }
            if store.monitorRunning { reasons.append("持续监控正在运行，退出会停止监控。") }
            if !reasons.isEmpty {
                let alert = NSAlert()
                alert.messageText = "确定退出交我选？"
                alert.informativeText = reasons.joined(separator: "\n")
                alert.alertStyle = .warning
                alert.addButton(withTitle: "退出")
                alert.addButton(withTitle: "取消")
                if alert.runModal() != .alertFirstButtonReturn { return .terminateCancel }
            }
            store.shutdown()
            return .terminateNow
        }
    }
}

struct AppCommands: Commands {
    let store: AppStore
    @Environment(\.openWindow) private var openWindow

    var body: some Commands {
        CommandGroup(replacing: .saveItem) {
            Button("保存方案") { Task { await store.saveGroups() } }
                .keyboardShortcut("s")
                .disabled(!store.groupsDirty || store.busy)
            Button("放弃方案修改") { store.revertGroups() }
                .disabled(!store.groupsDirty)
        }
        CommandGroup(before: .sidebar) {
            ForEach(Array(Page.allCases.enumerated()), id: \.element) { index, page in
                Button(page.title) {
                    openWindow(id: "main")
                    store.page = page
                }
                .keyboardShortcut(KeyEquivalent(Character(String(index + 1))))
            }
            Divider()
            Button("刷新") { Task { await store.refresh() } }
                .keyboardShortcut("r")
            Divider()
        }
        CommandMenu("监控") {
            Button("单次检查") { store.run("once") }
                .keyboardShortcut("o", modifiers: [.command, .shift])
                .disabled(store.running.contains("once"))
            if store.monitorRunning {
                Button("停止持续监控") { store.stop("monitor") }
                    .keyboardShortcut("m", modifiers: [.command, .shift])
            } else {
                Button("开始持续监控") { store.run("monitor") }
                    .keyboardShortcut("m", modifiers: [.command, .shift])
            }
            Divider()
            Button("获取全量课程") { store.run("bootstrap") }
                .disabled(store.running.contains("bootstrap"))
            Button("获取全部评价") { store.run("ratings-all") }
                .disabled(store.running.contains("ratings-all"))
            Button("读取教务当前学期") { store.run("detect-term") }
                .disabled(store.running.contains("detect-term"))
            if !store.releaseMode {
                Divider()
                Toggle("调试输出", isOn: Binding(get: { store.debug }, set: { store.debug = $0 }))
            }
        }
    }
}

struct MenuBarContent: View {
    @Environment(AppStore.self) private var store
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        Text(store.monitorRunning ? "持续监控中" : store.running.contains("once") ? "单次检查中" : "监控未运行")
        if let metrics = store.snapshot?.metrics {
            Text("监控目标 \(metrics.watched) · 自动换课\(metrics.autoSwap.label)")
        }
        Divider()
        Button("单次检查") { store.run("once") }
            .disabled(store.running.contains("once") || store.phase != .ready)
        if store.monitorRunning {
            Button("停止持续监控") { store.stop("monitor") }
        } else {
            Button("开始持续监控") { store.run("monitor") }
                .disabled(store.phase != .ready)
        }
        Divider()
        Button("打开交我选") {
            openWindow(id: "main")
            NSApp.activate(ignoringOtherApps: true)
        }
        SettingsLink { Text("设置…") }
        Divider()
        Button("退出") { NSApp.terminate(nil) }
            .keyboardShortcut("q")
    }
}
