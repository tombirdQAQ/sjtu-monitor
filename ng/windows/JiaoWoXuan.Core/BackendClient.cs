using System.Diagnostics;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace JiaoWoXuan.Core;

public sealed class BackendException(string code, string message) : Exception(message)
{
    public string Code { get; } = code;
}

public abstract record BackendEvent
{
    public sealed record Ready(HelloInfo Info) : BackendEvent;
    public sealed record ProcessOutput(string Task, LogEntry Entry) : BackendEvent;
    public sealed record ProcessExited(ProcessExit Exit) : BackendEvent;
    public sealed record Processes(List<string> Running) : BackendEvent;
    public sealed record StateChanged(List<string> Files) : BackendEvent;
    public sealed record Fatal(string Message) : BackendEvent;
    /// 服务进程本身退出(崩溃或被结束);StandardError 尾部用于诊断。
    public sealed record Terminated(int ExitCode, string StandardError) : BackendEvent;
}

/// 怎样启动 ng_service:打包 sidecar 或源码模式下的 python。
public sealed record BackendLaunch(
    string Executable,
    IReadOnlyList<string> Arguments,
    IReadOnlyDictionary<string, string> Environment,
    string WorkingDirectory,
    string Description);

public static class BackendLocator
{
    public const string DataIdentifier = "com.sj-tu.sjtu-monitor";

    /// 发行版数据目录与 Tauri 版一致(app_data_dir = %APPDATA%\<identifier>),两版共享数据。
    public static string ReleaseDataDirectory() =>
        Path.Combine(System.Environment.GetFolderPath(System.Environment.SpecialFolder.ApplicationData), DataIdentifier);

    /// 解析顺序:SJTU_MONITOR_ROOT(python gui.py --ng)→ 程序目录下的 sjtu-backend\sjtu-backend.exe
    /// → 从程序目录向上查找含 ng_service.py 的仓库。
    public static BackendLaunch Resolve(IDictionary<string, string>? environment = null, string? baseDirectory = null)
    {
        environment ??= System.Environment.GetEnvironmentVariables()
            .Cast<System.Collections.DictionaryEntry>()
            .ToDictionary(e => (string)e.Key, e => (string?)e.Value ?? "", StringComparer.OrdinalIgnoreCase);
        baseDirectory ??= AppContext.BaseDirectory;
        var env = new Dictionary<string, string>(environment, StringComparer.OrdinalIgnoreCase)
        {
            ["PYTHONUTF8"] = "1",
            ["PYTHONIOENCODING"] = "utf-8",
            ["PYTHONUNBUFFERED"] = "1",
        };

        if (NonEmpty(environment, "SJTU_MONITOR_ROOT") is { } root && IsRepo(root))
            return SourceLaunch(root, env);

        var sidecar = Path.Combine(baseDirectory, "sjtu-backend", "sjtu-backend.exe");
        if (File.Exists(sidecar))
        {
            var dataDir = ReleaseDataDirectory();
            Directory.CreateDirectory(dataDir);
            env["SJTU_MONITOR_RELEASE"] = "1";
            env["SJTU_MONITOR_DATA_DIR"] = dataDir;
            return new BackendLaunch(sidecar, ["ng_service.py"], env, dataDir, $"内置后端 {sidecar}");
        }

        for (var dir = new DirectoryInfo(baseDirectory); dir is not null; dir = dir.Parent)
        {
            if (IsRepo(dir.FullName)) return SourceLaunch(dir.FullName, env);
        }
        throw new BackendException("backend_not_found",
            "找不到 Python 后端。请在仓库根目录用 `python gui.py --ng` 启动，或设置 SJTU_MONITOR_ROOT。");
    }

    static BackendLaunch SourceLaunch(string root, Dictionary<string, string> env)
    {
        var python = PythonExecutable(root, env);
        env["SJTU_MONITOR_ROOT"] = root;
        env.Remove("SJTU_MONITOR_RELEASE");
        return new BackendLaunch(python, ["-u", Path.Combine(root, "ng_service.py")], env, root,
            $"源码后端 {python} @ {root}");
    }

    static string PythonExecutable(string root, IDictionary<string, string> env)
    {
        var home = System.Environment.GetFolderPath(System.Environment.SpecialFolder.UserProfile);
        var candidates = new List<string>();
        if (NonEmpty(env, "SJTU_MONITOR_PYTHON") is { } configured) candidates.Add(configured);
        candidates.Add(Path.Combine(root, ".venv", "Scripts", "python.exe"));
        foreach (var dist in new[] { "miniconda3", "anaconda3", "miniforge3" })
            candidates.Add(Path.Combine(home, dist, "envs", "sjtu-monitor", "python.exe"));
        candidates.Add(@"C:\ProgramData\miniconda3\envs\sjtu-monitor\python.exe");
        return candidates.FirstOrDefault(File.Exists)
            ?? throw new BackendException("python_not_found",
                "找不到 conda 环境 sjtu-monitor 的 Python。请设置 SJTU_MONITOR_PYTHON，或用 `python gui.py --ng` 启动。");
    }

    static bool IsRepo(string dir) => File.Exists(Path.Combine(dir, "ng_service.py"));

    static string? NonEmpty(IDictionary<string, string> env, string key) =>
        env.TryGetValue(key, out var value) && !string.IsNullOrWhiteSpace(value) ? value.Trim() : null;
}

/// ng_service 的 stdio 客户端。线程安全;事件回调在读取线程上触发,UI 层需自行切回 UI 线程。
public sealed class BackendClient(BackendLaunch launch, Action<BackendEvent> onEvent) : IDisposable
{
    readonly object gate = new();
    readonly Dictionary<long, TaskCompletionSource<JsonNode?>> pending = [];
    readonly StringBuilder stderrTail = new();
    Process? process;
    long nextId;
    bool terminated;

    public BackendLaunch Launch => launch;

    public bool IsRunning
    {
        get
        {
            lock (gate) return process is { HasExited: false };
        }
    }

    public void Start()
    {
        var info = new ProcessStartInfo(launch.Executable)
        {
            WorkingDirectory = launch.WorkingDirectory,
            RedirectStandardInput = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
            StandardInputEncoding = new UTF8Encoding(false),
            StandardOutputEncoding = new UTF8Encoding(false),
            StandardErrorEncoding = new UTF8Encoding(false),
        };
        foreach (var arg in launch.Arguments) info.ArgumentList.Add(arg);
        info.Environment.Clear();
        foreach (var (key, value) in launch.Environment) info.Environment[key] = value;

        var proc = new Process { StartInfo = info, EnableRaisingEvents = true };
        proc.ErrorDataReceived += (_, e) =>
        {
            if (e.Data is null) return;
            lock (stderrTail)
            {
                stderrTail.AppendLine(e.Data);
                if (stderrTail.Length > 16_000) stderrTail.Remove(0, stderrTail.Length - 8_000);
            }
        };
        if (!proc.Start())
            throw new BackendException("spawn_failed", $"无法启动后端：{launch.Description}");
        proc.StandardInput.AutoFlush = true;
        proc.StandardInput.NewLine = "\n";
        proc.BeginErrorReadLine();
        lock (gate) process = proc;
        var reader = new Thread(() => ReadLoop(proc)) { IsBackground = true, Name = "ng-backend-reader" };
        reader.Start();
    }

    /// 关闭 stdin:服务端结束它启动的子进程后自行退出。
    public void Shutdown(TimeSpan? timeout = null)
    {
        Process? proc;
        lock (gate) proc = process;
        if (proc is null) return;
        try { proc.StandardInput.Close(); } catch (Exception) { }
        if (!proc.WaitForExit(timeout ?? TimeSpan.FromSeconds(8)))
        {
            try { proc.Kill(entireProcessTree: true); } catch (Exception) { }
        }
    }

    public void Dispose() => Shutdown(TimeSpan.FromSeconds(3));

    public async Task<T> CallAsync<T>(string method, object? parameters = null, CancellationToken cancellationToken = default)
    {
        var node = await CallRawAsync(method, parameters, cancellationToken).ConfigureAwait(false);
        try
        {
            return node.Deserialize<T>(Json.Options)
                ?? throw new BackendException("decode_failed", $"{method} 返回为空");
        }
        catch (JsonException ex)
        {
            throw new BackendException("decode_failed", $"解析 {method} 返回值失败：{ex.Message}");
        }
    }

    public async Task<JsonNode?> CallRawAsync(string method, object? parameters, CancellationToken cancellationToken)
    {
        var tcs = new TaskCompletionSource<JsonNode?>(TaskCreationOptions.RunContinuationsAsynchronously);
        long id;
        Process proc;
        lock (gate)
        {
            if (terminated || process is null)
                throw new BackendException("backend_stopped", "后端服务未运行");
            id = ++nextId;
            pending[id] = tcs;
            proc = process;
        }
        var request = new JsonObject
        {
            ["id"] = id,
            ["method"] = method,
            ["params"] = JsonSerializer.SerializeToNode(parameters ?? new Dictionary<string, object?>(), Json.Options),
        };
        try
        {
            lock (proc.StandardInput)
            {
                proc.StandardInput.WriteLine(request.ToJsonString());
            }
        }
        catch (Exception ex) when (ex is IOException or ObjectDisposedException or InvalidOperationException)
        {
            lock (gate) pending.Remove(id);
            throw new BackendException("write_failed", $"无法写入后端：{ex.Message}");
        }
        using var registration = cancellationToken.Register(() =>
        {
            lock (gate) pending.Remove(id);
            tcs.TrySetCanceled(cancellationToken);
        });
        return await tcs.Task.ConfigureAwait(false);
    }

    void ReadLoop(Process proc)
    {
        try
        {
            while (proc.StandardOutput.ReadLine() is { } line)
            {
                if (line.Length > 0) Dispatch(line);
            }
        }
        catch (Exception ex) when (ex is IOException or ObjectDisposedException)
        {
        }
        proc.WaitForExit();
        List<TaskCompletionSource<JsonNode?>> waiting;
        lock (gate)
        {
            terminated = true;
            waiting = [.. pending.Values];
            pending.Clear();
        }
        var error = new BackendException("backend_stopped", $"后端服务已退出（status={proc.ExitCode}）");
        foreach (var tcs in waiting) tcs.TrySetException(error);
        string tail;
        lock (stderrTail) tail = stderrTail.ToString();
        onEvent(new BackendEvent.Terminated(proc.ExitCode, tail));
    }

    void Dispatch(string line)
    {
        JsonObject? message;
        try
        {
            message = JsonNode.Parse(line) as JsonObject;
        }
        catch (JsonException)
        {
            return;
        }
        if (message is null) return;

        if (message["event"]?.GetValue<string>() is { } name)
        {
            HandleEvent(name, message["data"]);
            return;
        }
        if (message["id"] is not JsonValue idValue || !idValue.TryGetValue<long>(out var id)) return;
        TaskCompletionSource<JsonNode?>? tcs;
        lock (gate)
        {
            if (!pending.Remove(id, out tcs)) return;
        }
        if (message["error"] is JsonObject error)
        {
            tcs.TrySetException(new BackendException(
                error["code"]?.GetValue<string>() ?? "error",
                error["message"]?.GetValue<string>() ?? "未知错误"));
            return;
        }
        tcs.TrySetResult(message["result"]?.DeepClone());
    }

    void HandleEvent(string name, JsonNode? data)
    {
        try
        {
            BackendEvent? evt = name switch
            {
                "ready" => new BackendEvent.Ready(data.Deserialize<HelloInfo>(Json.Options)!),
                "process.output" => new BackendEvent.ProcessOutput(
                    data?["task"]?.GetValue<string>() ?? "",
                    data?["entry"].Deserialize<LogEntry>(Json.Options) ?? new LogEntry()),
                "process.exited" => new BackendEvent.ProcessExited(data.Deserialize<ProcessExit>(Json.Options)!),
                "processes" => new BackendEvent.Processes(data.Deserialize<RunningResult>(Json.Options)!.Running),
                "state.changed" => new BackendEvent.StateChanged(
                    data?["files"].Deserialize<List<string>>(Json.Options) ?? []),
                "fatal" => new BackendEvent.Fatal(data?["message"]?.GetValue<string>() ?? "后端启动失败"),
                _ => null,
            };
            if (evt is not null) onEvent(evt);
        }
        catch (Exception ex) when (ex is JsonException or InvalidOperationException or NullReferenceException)
        {
        }
    }
}
