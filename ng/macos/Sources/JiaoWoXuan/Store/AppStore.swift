import AppKit
import Foundation
import JiaoWoXuanCore
import Observation

enum Page: String, CaseIterable, Identifiable, Hashable {
    case overview, courses, swap, snapshot, logs

    var id: String { rawValue }

    var title: String {
        switch self {
        case .overview: "总览"
        case .courses: "课程方案"
        case .swap: "自动换课"
        case .snapshot: "监控快照"
        case .logs: "日志"
        }
    }

    var symbol: String {
        switch self {
        case .overview: "gauge.with.dots.needle.33percent"
        case .courses: "books.vertical"
        case .swap: "arrow.triangle.swap"
        case .snapshot: "list.bullet.clipboard"
        case .logs: "text.alignleft"
        }
    }
}

enum StateFilter: String, CaseIterable, Identifiable {
    case watched, open, all
    var id: String { rawValue }
    var label: String {
        switch self {
        case .watched: "仅当前监控"
        case .open: "仅有空位"
        case .all: "全部"
        }
    }
}

enum BackendPhase: Equatable {
    case starting
    case ready
    case failed(String)
}

@MainActor
@Observable
final class AppStore {
    // MARK: 后端
    private(set) var phase: BackendPhase = .starting
    private(set) var hello: HelloInfo?
    private var client: BackendClient?

    // MARK: 数据
    private(set) var snapshot: Snapshot?
    var groups: [PriorityGroup] = [] { didSet { scheduleEvaluate() } }
    private var savedPlans: [PriorityGroup.Plan] = []
    private(set) var evaluations: [String: GroupEvaluation] = [:]
    var settings = SettingsPayload()
    private var savedSettings = SettingsPayload()
    private(set) var running: Set<String> = []
    private(set) var logs = LogsQueryResult(entries: [], counts: .zero)
    private(set) var bootstrapLines: [String] = []

    // MARK: 界面状态
    var page: Page = .overview
    var status = "正在启动后端服务"
    private(set) var busy = false
    var notice: Notice?
    var courseFilter = CourseFilter()
    var courseSelection: Set<String> = []
    var inspectedCourse: String?
    var selectedGroup: String?
    var memberSelection: Set<String> = []
    var logLevel: LogLevel? { didSet { reloadLogs() } }
    var logQuery = "" { didSet { reloadLogs() } }
    var stateFilter: StateFilter = .watched
    var debug = false
    var onboardingStep = 1

    private var evaluateTask: Task<Void, Never>?
    private var logsTask: Task<Void, Never>?
    private var snapshotTask: Task<Void, Never>?

    var releaseMode: Bool { hello?.releaseMode ?? snapshot?.releaseMode ?? false }
    var groupsDirty: Bool { groups.map(\.plan) != savedPlans }
    var settingsDirty: Bool { settings != savedSettings }
    var monitorRunning: Bool { running.contains("monitor") }
    var needsOnboarding: Bool { snapshot.map { !$0.onboarding.completed } ?? false }

    var courses: [CourseRow] { snapshot?.courses ?? [] }
    var coursesById: [String: CourseRow] {
        Dictionary(courses.map { ($0.jxbId, $0) }, uniquingKeysWith: { first, _ in first })
    }
    var filteredCourses: [CourseRow] { courseFilter.apply(to: courses) }
    var selectedGroupIndex: Int? { groups.firstIndex { $0.name == selectedGroup } }

    var stateRows: [StateRow] {
        let rows = snapshot?.stateRows ?? []
        switch stateFilter {
        case .watched: return rows.filter(\.watched)
        case .open: return rows.filter { $0.open == true }
        case .all: return rows
        }
    }

    func conflicts(for group: PriorityGroup) -> [String: ConflictMark] {
        evaluations[group.name]?.conflicts ?? group.conflicts
    }

    func heldLabel(for group: PriorityGroup) -> String {
        evaluations[group.name]?.heldLabel ?? group.heldLabel
    }

    // MARK: - 生命周期

    func start() {
        guard client == nil else { return }
        phase = .starting
        status = "正在启动后端服务"
        do {
            let launch = try BackendLocator.resolve()
            let client = BackendClient(launch: launch) { [weak self] event in
                Task { @MainActor in self?.handle(event) }
            }
            try client.start()
            self.client = client
        } catch {
            phase = .failed(error.localizedDescription)
            status = error.localizedDescription
        }
    }

    func restartBackend() {
        client?.shutdown(timeout: 3)
        client = nil
        start()
    }

    func shutdown() {
        client?.shutdown()
        client = nil
    }

    private func handle(_ event: BackendEvent) {
        switch event {
        case .ready(let info):
            hello = info
            running = Set(info.running)
            phase = .ready
            Task { await refresh() }
        case .processOutput(let task, let entry):
            if task == "bootstrap" {
                bootstrapLines = Array((bootstrapLines + [entry.message]).suffix(8))
            }
            scheduleLogsReload()
        case .processExited(let exit):
            running.remove(exit.task)
            scheduleLogsReload()
            if let notice = exit.notice {
                self.notice = notice
                SystemNotifier.post(title: notice.title, body: notice.message)
            } else if exit.task == "detect-term", exit.code == 0, let label = exit.result?.siteTerm?.label {
                status = "教务网站当前选课学期：\(label)"
            } else if exit.task == "bootstrap", exit.code == 0 {
                status = "课程目录已同步"
            }
            // 不用 refresh():抓取结束时用户可能正在编辑方案,不能丢掉未保存的修改。
            scheduleSnapshotReload()
        case .processes(let tasks):
            running = Set(tasks)
        case .stateChanged(let files):
            if files.contains("changes_log") { scheduleLogsReload() }
            if files.contains(where: { $0 != "changes_log" }) || snapshot == nil {
                scheduleSnapshotReload()
            }
        case .fatal(let message):
            phase = .failed(message)
            status = message
        case .terminated(let code, let stderr):
            client = nil
            running = []
            let tail = stderr.split(separator: "\n").suffix(3).joined(separator: "\n")
            let message = "后端服务已退出（status=\(code)）" + (tail.isEmpty ? "" : "\n\(tail)")
            phase = .failed(message)
            status = message
        }
    }

    // MARK: - 快照

    private func backend() throws -> BackendClient {
        guard let client, phase == .ready else {
            throw BackendError(code: "backend_stopped", message: "后端服务未就绪")
        }
        return client
    }

    func refresh() async {
        do {
            let data = try await backend().call("snapshot", as: Snapshot.self)
            apply(data, replaceEdits: true)
            status = "已刷新 \(data.generatedAt)"
        } catch {
            status = error.localizedDescription
        }
    }

    /// 后台触发的刷新:用户正在编辑的方案/设置不被覆盖。
    private func scheduleSnapshotReload() {
        snapshotTask?.cancel()
        snapshotTask = Task {
            try? await Task.sleep(for: .milliseconds(400))
            guard !Task.isCancelled, !busy else { return }
            guard let data = try? await backend().call("snapshot", as: Snapshot.self) else { return }
            apply(data, replaceEdits: false)
        }
    }

    private func apply(_ data: Snapshot, replaceEdits: Bool) {
        let groupsWereDirty = groupsDirty
        let settingsWereDirty = settingsDirty
        snapshot = data
        running = Set(data.running)
        if replaceEdits || !groupsWereDirty {
            savedPlans = data.groups.map(\.plan)
            evaluations = [:]
            groups = data.groups
        }
        if replaceEdits || !settingsWereDirty {
            settings = data.settings
        }
        savedSettings = data.settings
        if selectedGroup == nil || !groups.contains(where: { $0.name == selectedGroup }) {
            selectedGroup = groups.first?.name
        }
        if !data.onboarding.completed {
            onboardingStep = data.onboarding.catalogReady ? 3 : (data.onboarding.hasAccount ? 2 : 1)
        }
    }

    private func scheduleEvaluate() {
        evaluateTask?.cancel()
        guard groupsDirty, phase == .ready else {
            if !groupsDirty { evaluations = [:] }
            return
        }
        let payload: [[String: Any]] = groups.map { ["name": $0.name, "is_pe": $0.isPe, "priority": $0.priority] }
        evaluateTask = Task {
            try? await Task.sleep(for: .milliseconds(150))
            guard !Task.isCancelled else { return }
            guard let result = try? await backend().call(
                "groups.evaluate", ["groups": payload], as: GroupsEvaluateResult.self
            ) else { return }
            guard !Task.isCancelled else { return }
            evaluations = Dictionary(result.groups.map { ($0.name, $0) }, uniquingKeysWith: { _, last in last })
        }
    }

    // MARK: - 日志

    func reloadLogs() {
        logsTask?.cancel()
        let level = logLevel?.rawValue ?? "all"
        let query = logQuery
        logsTask = Task {
            guard let result = try? await backend().call(
                "logs.query", ["level": level, "query": query, "limit": 800], as: LogsQueryResult.self
            ) else { return }
            guard !Task.isCancelled else { return }
            logs = result
        }
    }

    private func scheduleLogsReload() {
        guard page == .logs else { return }
        logsTask?.cancel()
        logsTask = Task {
            try? await Task.sleep(for: .milliseconds(250))
            guard !Task.isCancelled else { return }
            reloadLogs()
        }
    }

    // MARK: - 进程

    func run(_ task: String, adoptSiteTerm: Bool = false) {
        Task {
            do {
                var params: [String: Any] = ["task": task, "debug": debug && !releaseMode]
                if adoptSiteTerm { params["adopt_site_term"] = true }
                let result = try await backend().call("process.start", params, as: RunningResult.self)
                running = Set(result.running)
                if task == "bootstrap" { bootstrapLines = [] }
            } catch {
                status = error.localizedDescription
            }
        }
    }

    func stop(_ task: String) {
        Task {
            do {
                let result = try await backend().call("process.stop", ["task": task], as: RunningResult.self)
                running = Set(result.running)
            } catch {
                status = error.localizedDescription
            }
        }
    }

    // MARK: - 学期

    func switchTerm(xkxnm: String, xkxqm: String) async {
        await perform {
            let result = try await self.backend().call(
                "term.switch", ["xkxnm": xkxnm, "xkxqm": xkxqm], as: SwitchTermResult.self
            )
            self.courseSelection = []
            self.inspectedCourse = nil
            self.selectedGroup = nil
            self.memberSelection = []
            await self.refresh()
            self.status = self.monitorRunning
                ? "已切换到 \(result.activeTerm)；正在运行的监控仍按原学期执行，重启监控后生效"
                : "已切换到 \(result.activeTerm)"
        }
    }

    // MARK: - 方案编辑

    func createGroup(named rawName: String) -> Bool {
        let name = rawName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty, !groups.contains(where: { $0.name == name }) else { return false }
        groups.append(PriorityGroup(name: name))
        selectedGroup = name
        status = "已新建方案 \(name)，尚未保存"
        return true
    }

    func deleteSelectedGroup() {
        guard let index = selectedGroupIndex else { return }
        let name = groups[index].name
        groups.remove(at: index)
        selectedGroup = groups.first?.name
        memberSelection = []
        status = "已删除方案 \(name)，尚未保存"
    }

    /// 返回冲突提示文案(有冲突时只警告,仍然加入)。
    func addCourses(_ ids: [String]) async -> String? {
        guard let index = selectedGroupIndex else {
            status = "请先选择或新建一个方案"
            return nil
        }
        let group = groups[index]
        do {
            let result = try await backend().call(
                "groups.add_courses", ["priority": group.priority, "added": ids], as: AddCoursesResult.self
            )
            guard !result.added.isEmpty else {
                status = "所选教学班已在“\(group.name)”中"
                return nil
            }
            if let current = groups.firstIndex(where: { $0.name == group.name }) {
                groups[current].priority = result.priority
            }
            courseSelection = []
            status = "已加入 \(result.added.count) 个教学班到“\(group.name)”，尚未保存"
            return result.warning
        } catch {
            status = error.localizedDescription
            return nil
        }
    }

    func moveMembers(from source: IndexSet, to destination: Int) {
        guard let index = selectedGroupIndex else { return }
        groups[index].priority.move(fromOffsets: source, toOffset: destination)
    }

    func moveSelectedMember(by delta: Int) {
        guard let index = selectedGroupIndex, memberSelection.count == 1, let id = memberSelection.first,
              let position = groups[index].priority.firstIndex(of: id) else { return }
        let target = position + delta
        guard groups[index].priority.indices.contains(target) else { return }
        groups[index].priority.swapAt(position, target)
    }

    func setAsHeld(_ id: String) {
        guard let index = selectedGroupIndex else { return }
        groups[index].priority.removeAll { $0 == id }
        groups[index].priority.append(id)
    }

    func removeMembers(_ ids: Set<String>) {
        guard let index = selectedGroupIndex, !ids.isEmpty else { return }
        groups[index].priority.removeAll { ids.contains($0) }
        memberSelection.subtract(ids)
    }

    func setPE(_ value: Bool) {
        guard let index = selectedGroupIndex else { return }
        groups[index].isPe = value
    }

    func revertGroups() {
        guard let snapshot else { return }
        groups = snapshot.groups
        savedPlans = snapshot.groups.map(\.plan)
        if !groups.contains(where: { $0.name == selectedGroup }) { selectedGroup = groups.first?.name }
        status = "已放弃未保存的方案修改"
    }

    func saveGroups() async {
        await perform {
            var payload: [String: Any] = [:]
            for group in self.groups {
                payload[group.name] = ["is_pe": group.isPe, "priority": group.priority]
            }
            let result = try await self.backend().call("groups.save", ["groups": payload], as: SaveGroupsResult.self)
            await self.refresh()
            let warnings = result.warnings
                + result.duplicates.map { "\(Self.shortId($0.key)) 重复: \($0.value.joined(separator: ", "))" }
                + result.unresolved.map { "\(Self.shortId($0)) 无法推导查询模板" }
            if warnings.isEmpty {
                self.status = "方案已保存，共监控 \(result.courseCount) 门课程"
            } else {
                self.status = "方案已保存，但有 \(warnings.count) 条提示"
                self.notice = Notice(title: "方案已保存", message: warnings.joined(separator: "\n"))
            }
        }
    }

    // MARK: - 设置与引导

    func saveSettings() async {
        await perform {
            _ = try await self.backend().call("settings.save", self.settings.requestParams, as: OkResult.self)
            await self.refresh()
            self.status = "设置已保存；正在运行的监控需重启后使用新参数"
        }
    }

    func sendTestEmail() async {
        status = "正在保存设置并发送测试邮件…"
        await perform {
            _ = try await self.backend().call("settings.save", self.settings.requestParams, as: OkResult.self)
            let result = try await self.backend().call("settings.test_email", as: TestEmailResult.self)
            await self.refresh()
            self.status = "测试邮件已发送至 \(result.mailTo ?? "收件人")，请查收"
        }
    }

    func saveOnboardingAccount() async {
        guard !settings.jaccountUser.trimmingCharacters(in: .whitespaces).isEmpty else {
            status = "请输入 JAccount 账号"
            return
        }
        guard !settings.jaccountPass.isEmpty || settings.hasJaccountPass == true else {
            status = "请输入 JAccount 密码"
            return
        }
        await perform {
            _ = try await self.backend().call("settings.save", self.settings.requestParams, as: OkResult.self)
            await self.refresh()
            self.onboardingStep = 2
            self.status = "账号已安全保存；同步只会在你点击按钮后开始"
        }
    }

    func finishOnboarding() async {
        await perform {
            _ = try await self.backend().call("onboarding.complete", as: OkResult.self)
            await self.refresh()
            self.page = .courses
            self.status = "初始化完成，请创建你的选课方案"
        }
    }

    func setAutoSwap(enabled: Bool, dryRun: Bool) async {
        await perform {
            _ = try await self.backend().call("autoswap.set", ["enabled": enabled, "dry_run": dryRun], as: OkResult.self)
            await self.refresh()
            self.status = "自动换课设置已保存；重启监控后生效"
        }
    }

    private func perform(_ action: @escaping () async throws -> Void) async {
        busy = true
        defer { busy = false }
        do {
            try await action()
        } catch {
            status = error.localizedDescription
            notice = Notice(title: "操作失败", message: error.localizedDescription)
        }
    }

    static func shortId(_ value: String?) -> String {
        guard let value, !value.isEmpty else { return "-" }
        return value.count > 18 ? "\(value.prefix(8))…\(value.suffix(6))" : value
    }
}
