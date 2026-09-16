import Foundation

public struct BackendError: LocalizedError, Sendable {
    public var code: String
    public var message: String

    public init(code: String, message: String) {
        self.code = code
        self.message = message
    }

    public var errorDescription: String? { message }
}

public enum BackendEvent: Sendable {
    case ready(HelloInfo)
    case processOutput(task: String, entry: LogEntry)
    case processExited(ProcessExit)
    case processes([String])
    case stateChanged([String])
    case fatal(String)
    /// 服务进程本身退出(崩溃或被结束);stderr 尾部用于诊断。
    case terminated(status: Int32, stderr: String)
}

/// 怎样启动 ng_service:打包 sidecar 或源码模式下的 python。
public struct BackendLaunch: Sendable, Equatable {
    public var executable: URL
    public var arguments: [String]
    public var environment: [String: String]
    public var workingDirectory: URL
    public var description: String

    public init(executable: URL, arguments: [String], environment: [String: String], workingDirectory: URL, description: String) {
        self.executable = executable
        self.arguments = arguments
        self.environment = environment
        self.workingDirectory = workingDirectory
        self.description = description
    }
}

public enum BackendLocator {
    public static let bundleIdentifier = "com.sj-tu.sjtu-monitor"

    /// 发行版数据目录与 Tauri 版一致(app_data_dir = Application Support/<identifier>),两版共享数据。
    public static func releaseDataDirectory(fileManager: FileManager = .default) -> URL {
        let base = fileManager.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Library/Application Support")
        return base.appendingPathComponent(bundleIdentifier, isDirectory: true)
    }

    /// 解析顺序:
    /// 1. `SJTU_MONITOR_ROOT` 指定的仓库(源码模式,`python gui.py --ng` 会设置);
    /// 2. .app 内 `Resources/sjtu-backend/sjtu-backend`(发行版 sidecar);
    /// 3. 从可执行文件向上找含 ng_service.py 的目录(开发时 `swift run`)。
    public static func resolve(
        environment: [String: String] = ProcessInfo.processInfo.environment,
        bundle: Bundle = .main,
        fileManager: FileManager = .default
    ) throws -> BackendLaunch {
        var baseEnv = environment
        baseEnv["PYTHONUTF8"] = "1"
        baseEnv["PYTHONIOENCODING"] = "utf-8"
        baseEnv["PYTHONUNBUFFERED"] = "1"

        if let root = environment["SJTU_MONITOR_ROOT"].flatMap(nonEmpty), isRepo(URL(fileURLWithPath: root), fileManager) {
            return try sourceLaunch(root: URL(fileURLWithPath: root), environment: baseEnv, fileManager: fileManager)
        }

        if let resources = bundle.resourceURL {
            let sidecar = resources.appendingPathComponent("sjtu-backend/sjtu-backend")
            if fileManager.isExecutableFile(atPath: sidecar.path) {
                let dataDir = releaseDataDirectory(fileManager: fileManager)
                try? fileManager.createDirectory(at: dataDir, withIntermediateDirectories: true)
                var env = baseEnv
                env["SJTU_MONITOR_RELEASE"] = "1"
                env["SJTU_MONITOR_DATA_DIR"] = dataDir.path
                return BackendLaunch(
                    executable: sidecar,
                    arguments: ["ng_service.py"],
                    environment: env,
                    workingDirectory: dataDir,
                    description: "内置后端 \(sidecar.path)"
                )
            }
        }

        let starts = [bundle.executableURL, URL(fileURLWithPath: fileManager.currentDirectoryPath)].compactMap { $0 }
        for start in starts {
            var dir = start.deletingLastPathComponent()
            while dir.path != "/" {
                if isRepo(dir, fileManager) {
                    return try sourceLaunch(root: dir, environment: baseEnv, fileManager: fileManager)
                }
                dir.deleteLastPathComponent()
            }
        }
        throw BackendError(
            code: "backend_not_found",
            message: "找不到 Python 后端。请在仓库根目录用 `python gui.py --ng` 启动，或设置 SJTU_MONITOR_ROOT。"
        )
    }

    static func sourceLaunch(root: URL, environment: [String: String], fileManager: FileManager) throws -> BackendLaunch {
        let python = try pythonExecutable(root: root, environment: environment, fileManager: fileManager)
        var env = environment
        env["SJTU_MONITOR_ROOT"] = root.path
        env.removeValue(forKey: "SJTU_MONITOR_RELEASE")
        return BackendLaunch(
            executable: python,
            arguments: ["-u", root.appendingPathComponent("ng_service.py").path],
            environment: env,
            workingDirectory: root,
            description: "源码后端 \(python.path) @ \(root.path)"
        )
    }

    static func pythonExecutable(root: URL, environment: [String: String], fileManager: FileManager) throws -> URL {
        var candidates: [String] = []
        if let configured = environment["SJTU_MONITOR_PYTHON"].flatMap(nonEmpty) {
            candidates.append(configured)
        }
        candidates.append(root.appendingPathComponent(".venv/bin/python").path)
        let home = NSHomeDirectory()
        for base in ["miniconda3", "anaconda3", "miniforge3", "opt/miniconda3", "opt/anaconda3"] {
            candidates.append("\(home)/\(base)/envs/sjtu-monitor/bin/python")
        }
        candidates.append("/opt/homebrew/Caskroom/miniconda/base/envs/sjtu-monitor/bin/python")
        for path in candidates where fileManager.isExecutableFile(atPath: path) {
            return URL(fileURLWithPath: path)
        }
        throw BackendError(
            code: "python_not_found",
            message: "找不到 conda 环境 sjtu-monitor 的 Python。请设置 SJTU_MONITOR_PYTHON，或用 `python gui.py --ng` 启动。"
        )
    }

    static func isRepo(_ url: URL, _ fileManager: FileManager) -> Bool {
        fileManager.fileExists(atPath: url.appendingPathComponent("ng_service.py").path)
    }

    static func nonEmpty(_ value: String) -> String? {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }
}

/// ng_service 的 stdio 客户端。线程安全;事件回调在内部串行队列上触发。
public final class BackendClient: @unchecked Sendable {
    public typealias EventHandler = @Sendable (BackendEvent) -> Void

    private let launch: BackendLaunch
    private let onEvent: EventHandler
    private let queue = DispatchQueue(label: "ng.backend.client")
    private var process: Process?
    private var stdin: FileHandle?
    private var buffer = Data()
    private var stderrTail = Data()
    private var nextId = 0
    private var pending: [Int: CheckedContinuation<Data, Error>] = [:]
    private var terminated = false

    public init(launch: BackendLaunch, onEvent: @escaping EventHandler) {
        self.launch = launch
        self.onEvent = onEvent
    }

    public func start() throws {
        let process = Process()
        process.executableURL = launch.executable
        process.arguments = launch.arguments
        process.environment = launch.environment
        process.currentDirectoryURL = launch.workingDirectory
        let stdinPipe = Pipe()
        let stdoutPipe = Pipe()
        let stderrPipe = Pipe()
        process.standardInput = stdinPipe
        process.standardOutput = stdoutPipe
        process.standardError = stderrPipe

        stdoutPipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            self?.queue.async { self?.consume(data) }
        }
        stderrPipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty else { return }
            FileHandle.standardError.write(data)
            self?.queue.async {
                guard let self else { return }
                self.stderrTail.append(data)
                if self.stderrTail.count > 16_000 {
                    self.stderrTail = self.stderrTail.suffix(8_000)
                }
            }
        }
        process.terminationHandler = { [weak self] proc in
            stdoutPipe.fileHandleForReading.readabilityHandler = nil
            stderrPipe.fileHandleForReading.readabilityHandler = nil
            self?.queue.async { self?.handleTermination(status: proc.terminationStatus) }
        }
        try process.run()
        queue.sync {
            self.process = process
            self.stdin = stdinPipe.fileHandleForWriting
        }
    }

    /// 关闭 stdin:服务端结束它启动的子进程后自行退出。
    public func shutdown(timeout: TimeInterval = 8) {
        let (handle, process) = queue.sync { (stdin, self.process) }
        try? handle?.close()
        guard let process else { return }
        let deadline = Date().addingTimeInterval(timeout)
        while process.isRunning && Date() < deadline {
            Thread.sleep(forTimeInterval: 0.05)
        }
        if process.isRunning { process.terminate() }
    }

    public var isRunning: Bool { queue.sync { process?.isRunning ?? false } }

    public func call<T: Decodable>(_ method: String, _ params: [String: Any] = [:], as type: T.Type = T.self) async throws -> T {
        let data = try await callRaw(method, params)
        do {
            return try JSONDecoder().decode(T.self, from: data)
        } catch {
            throw BackendError(code: "decode_failed", message: "解析 \(method) 返回值失败：\(error)")
        }
    }

    public func callRaw(_ method: String, _ params: [String: Any]) async throws -> Data {
        let body: Data
        do {
            body = try JSONSerialization.data(withJSONObject: params)
        } catch {
            throw BackendError(code: "invalid_params", message: "参数无法编码：\(error)")
        }
        return try await withCheckedThrowingContinuation { continuation in
            queue.async {
                guard !self.terminated, let stdin = self.stdin else {
                    continuation.resume(throwing: BackendError(code: "backend_stopped", message: "后端服务未运行"))
                    return
                }
                self.nextId += 1
                let id = self.nextId
                self.pending[id] = continuation
                var line = Data("{\"id\":\(id),\"method\":".utf8)
                line.append((try? JSONSerialization.data(withJSONObject: method, options: .fragmentsAllowed)) ?? Data("\"\"".utf8))
                line.append(Data(",\"params\":".utf8))
                line.append(body)
                line.append(Data("}\n".utf8))
                do {
                    try stdin.write(contentsOf: line)
                } catch {
                    self.pending.removeValue(forKey: id)
                    continuation.resume(throwing: BackendError(code: "write_failed", message: "无法写入后端：\(error)"))
                }
            }
        }
    }

    // MARK: - 仅在 queue 上调用

    private func consume(_ data: Data) {
        guard !data.isEmpty else { return }
        buffer.append(data)
        while let newline = buffer.firstIndex(of: 0x0A) {
            let line = buffer[buffer.startIndex..<newline]
            buffer.removeSubrange(buffer.startIndex...newline)
            if !line.isEmpty { dispatch(Data(line)) }
        }
    }

    private func dispatch(_ line: Data) {
        guard let object = try? JSONSerialization.jsonObject(with: line) as? [String: Any] else {
            return
        }
        if let event = object["event"] as? String {
            handleEvent(event, object["data"])
            return
        }
        guard let id = object["id"] as? Int, let continuation = pending.removeValue(forKey: id) else {
            return
        }
        if let error = object["error"] as? [String: Any] {
            continuation.resume(throwing: BackendError(
                code: error["code"] as? String ?? "error",
                message: error["message"] as? String ?? "未知错误"
            ))
            return
        }
        let result = object["result"] ?? NSNull()
        do {
            continuation.resume(returning: try JSONSerialization.data(withJSONObject: result, options: .fragmentsAllowed))
        } catch {
            continuation.resume(throwing: error)
        }
    }

    private func handleEvent(_ name: String, _ payload: Any?) {
        let data = payload.flatMap { try? JSONSerialization.data(withJSONObject: $0, options: .fragmentsAllowed) } ?? Data("{}".utf8)
        let decoder = JSONDecoder()
        switch name {
        case "ready":
            if let info = try? decoder.decode(HelloInfo.self, from: data) { onEvent(.ready(info)) }
        case "process.output":
            struct Output: Decodable { var task: String; var entry: LogEntry }
            if let output = try? decoder.decode(Output.self, from: data) {
                onEvent(.processOutput(task: output.task, entry: output.entry))
            }
        case "process.exited":
            if let exit = try? decoder.decode(ProcessExit.self, from: data) { onEvent(.processExited(exit)) }
        case "processes":
            if let result = try? decoder.decode(RunningResult.self, from: data) { onEvent(.processes(result.running)) }
        case "state.changed":
            struct Changed: Decodable { var files: [String] }
            if let changed = try? decoder.decode(Changed.self, from: data) { onEvent(.stateChanged(changed.files)) }
        case "fatal":
            let message = (payload as? [String: Any])?["message"] as? String ?? "后端启动失败"
            onEvent(.fatal(message))
        default:
            break
        }
    }

    private func handleTermination(status: Int32) {
        terminated = true
        let error = BackendError(code: "backend_stopped", message: "后端服务已退出（status=\(status)）")
        for continuation in pending.values { continuation.resume(throwing: error) }
        pending.removeAll()
        let tail = String(decoding: stderrTail, as: UTF8.self)
        onEvent(.terminated(status: status, stderr: tail))
    }
}
