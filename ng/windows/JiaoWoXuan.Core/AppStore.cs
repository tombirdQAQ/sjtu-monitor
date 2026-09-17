using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Runtime.CompilerServices;

namespace JiaoWoXuan.Core;

public enum Page { Overview, Courses, Swap, Snapshot, Logs, Settings }

public enum StateFilter { Watched, Open, All }

public enum BackendPhase { Starting, Ready, Failed }

public abstract class ObservableObject : INotifyPropertyChanged
{
    public event PropertyChangedEventHandler? PropertyChanged;

    protected bool Set<T>(ref T field, T value, [CallerMemberName] string? name = null)
    {
        if (EqualityComparer<T>.Default.Equals(field, value)) return false;
        field = value;
        Raise(name);
        return true;
    }

    protected void Raise([CallerMemberName] string? name = null) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
}

/// 应用状态(与 macOS 版 AppStore 对应)。不依赖 WinUI:所有回调经 dispatch 切回 UI 线程,
/// 便于在单测里直接驱动。
public sealed class AppStore(Action<Action> dispatch, Func<BackendLaunch>? resolveLaunch = null) : ObservableObject
{
    readonly Func<BackendLaunch> resolveLaunch = resolveLaunch ?? (() => BackendLocator.Resolve());
    BackendClient? client;
    List<string> savedPlans = [];
    SettingsPayload savedSettings = new();
    CancellationTokenSource? evaluateCts;
    CancellationTokenSource? snapshotCts;
    CancellationTokenSource? logsCts;

    /// 通知(错误提示、冲突提示、抓取失败)。UI 层弹 ContentDialog。
    public event Action<Notice>? NoticeRaised;

    /// 抓取失败等需要系统通知的事件;UI 层在窗口不在前台时发 Toast。
    public event Action<Notice>? SystemNotification;

    BackendPhase phase = BackendPhase.Starting;
    public BackendPhase Phase { get => phase; private set { if (Set(ref phase, value)) Raise(nameof(IsReady)); } }
    public bool IsReady => Phase == BackendPhase.Ready;

    string failure = "";
    public string Failure { get => failure; private set => Set(ref failure, value); }

    HelloInfo? hello;
    public HelloInfo? Hello { get => hello; private set { if (Set(ref hello, value)) Raise(nameof(ReleaseMode)); } }

    Snapshot? snapshot;
    public Snapshot? Snapshot { get => snapshot; private set => Set(ref snapshot, value); }

    public ObservableCollection<PriorityGroup> Groups { get; } = [];

    Dictionary<string, GroupEvaluation> evaluations = [];
    public IReadOnlyDictionary<string, GroupEvaluation> Evaluations => evaluations;

    SettingsPayload settings = new();
    public SettingsPayload Settings
    {
        get => settings;
        set { if (Set(ref settings, value)) Raise(nameof(SettingsDirty)); }
    }

    HashSet<string> running = [];
    public IReadOnlySet<string> Running => running;
    public bool MonitorRunning => running.Contains("monitor");

    LogsQueryResult logs = new();
    public LogsQueryResult Logs { get => logs; private set => Set(ref logs, value); }

    public ObservableCollection<string> BootstrapLines { get; } = [];

    string status = "正在启动后端服务";
    public string Status { get => status; set => Set(ref status, value); }

    bool busy;
    public bool Busy { get => busy; private set => Set(ref busy, value); }

    Page page = Page.Overview;
    public Page Page { get => page; set { if (Set(ref page, value) && value == Page.Logs) ReloadLogs(); } }

    string? selectedGroup;
    public string? SelectedGroup { get => selectedGroup; set { if (Set(ref selectedGroup, value)) Raise(nameof(SelectedGroupData)); } }

    CourseFilter courseFilter = new();
    public CourseFilter CourseFilter
    {
        get => courseFilter;
        set { if (Set(ref courseFilter, value)) Raise(nameof(FilteredCourses)); }
    }

    LogLevel? logLevel;
    public LogLevel? LogLevel { get => logLevel; set { if (Set(ref logLevel, value)) ReloadLogs(); } }

    string logQuery = "";
    public string LogQuery { get => logQuery; set { if (Set(ref logQuery, value)) ReloadLogs(); } }

    StateFilter stateFilter = StateFilter.Watched;
    public StateFilter StateFilter { get => stateFilter; set { if (Set(ref stateFilter, value)) Raise(nameof(StateRows)); } }

    bool debug;
    public bool Debug { get => debug; set => Set(ref debug, value); }

    int onboardingStep = 1;
    public int OnboardingStep { get => onboardingStep; set => Set(ref onboardingStep, value); }

    public bool ReleaseMode => Hello?.ReleaseMode ?? Snapshot?.ReleaseMode ?? false;
    public bool NeedsOnboarding => Snapshot is { Onboarding.Completed: false };
    public bool GroupsDirty => !Groups.Select(g => g.PlanSignature).SequenceEqual(savedPlans);
    public bool SettingsDirty => Settings != savedSettings;

    public IReadOnlyList<CourseRow> Courses => Snapshot?.Courses ?? [];

    Dictionary<string, CourseRow> coursesById = [];
    public IReadOnlyDictionary<string, CourseRow> CoursesById => coursesById;

    CourseSortOrder courseSort = new();
    public CourseSortOrder CourseSort
    {
        get => courseSort;
        set { if (Set(ref courseSort, value)) Raise(nameof(FilteredCourses)); }
    }

    public List<CourseRow> FilteredCourses => CourseFilter.Apply(Courses, CourseSort);

    public PriorityGroup? SelectedGroupData => Groups.FirstOrDefault(g => g.Name == SelectedGroup);

    public List<StateRow> StateRows => StateFilter switch
    {
        StateFilter.Watched => Snapshot?.StateRows.Where(r => r.Watched).ToList() ?? [],
        StateFilter.Open => Snapshot?.StateRows.Where(r => r.Open == true).ToList() ?? [],
        _ => Snapshot?.StateRows ?? [],
    };

    public IReadOnlyDictionary<string, ConflictMark> ConflictsFor(PriorityGroup group) =>
        evaluations.TryGetValue(group.Name, out var evaluation) ? evaluation.Conflicts : group.Conflicts;

    public string HeldLabelFor(PriorityGroup group) =>
        evaluations.TryGetValue(group.Name, out var evaluation) ? evaluation.HeldLabel : group.HeldLabel;

    // ------------------------------------------------------------ 生命周期

    public void Start()
    {
        if (client is not null) return;
        Phase = BackendPhase.Starting;
        Status = "正在启动后端服务";
        try
        {
            var launched = new BackendClient(resolveLaunch(), evt => dispatch(() => Handle(evt)));
            launched.Start();
            client = launched;
        }
        catch (Exception ex)
        {
            Fail(ex.Message);
        }
    }

    public void RestartBackend()
    {
        client?.Shutdown(TimeSpan.FromSeconds(3));
        client = null;
        Start();
    }

    public void Shutdown()
    {
        client?.Shutdown();
        client = null;
    }

    void Fail(string message)
    {
        Failure = message;
        Status = message;
        Phase = BackendPhase.Failed;
    }

    void SetRunning(IEnumerable<string> tasks)
    {
        running = [.. tasks];
        Raise(nameof(Running));
        Raise(nameof(MonitorRunning));
    }

    void Handle(BackendEvent evt)
    {
        switch (evt)
        {
            case BackendEvent.Ready ready:
                Hello = ready.Info;
                SetRunning(ready.Info.Running);
                Phase = BackendPhase.Ready;
                _ = RefreshAsync();
                break;
            case BackendEvent.ProcessOutput output:
                if (output.Task == "bootstrap")
                {
                    BootstrapLines.Add(output.Entry.Message);
                    while (BootstrapLines.Count > 8) BootstrapLines.RemoveAt(0);
                }
                ScheduleLogsReload();
                break;
            case BackendEvent.ProcessExited exited:
                running.Remove(exited.Exit.Task);
                SetRunning(running);
                ScheduleLogsReload();
                if (exited.Exit.Notice is { } notice)
                {
                    NoticeRaised?.Invoke(notice);
                    SystemNotification?.Invoke(notice);
                }
                else if (exited.Exit is { Task: "detect-term", Code: 0, Result.SiteTermLabel: { } label })
                {
                    Status = $"教务网站当前选课学期：{label}";
                }
                else if (exited.Exit is { Task: "bootstrap", Code: 0 })
                {
                    Status = "课程目录已同步";
                }
                // 不整体刷新:抓取结束时用户可能正在编辑方案,不能丢掉未保存的修改。
                ScheduleSnapshotReload();
                break;
            case BackendEvent.Processes processes:
                SetRunning(processes.Running);
                break;
            case BackendEvent.StateChanged changed:
                if (changed.Files.Contains("changes_log")) ScheduleLogsReload();
                if (changed.Files.Any(f => f != "changes_log") || Snapshot is null) ScheduleSnapshotReload();
                break;
            case BackendEvent.Fatal fatal:
                Fail(fatal.Message);
                break;
            case BackendEvent.Terminated terminated:
                client = null;
                SetRunning([]);
                var tail = string.Join("\n", terminated.StandardError.Split('\n', StringSplitOptions.RemoveEmptyEntries).TakeLast(3));
                Fail($"后端服务已退出（status={terminated.ExitCode}）" + (tail.Length > 0 ? "\n" + tail : ""));
                break;
        }
    }

    BackendClient Backend() =>
        client is not null && Phase == BackendPhase.Ready
            ? client
            : throw new BackendException("backend_stopped", "后端服务未就绪");

    /// await 之后切回 UI 线程继续。
    Task<T> OnUi<T>(Task<T> task)
    {
        var tcs = new TaskCompletionSource<T>();
        task.ContinueWith(t => dispatch(() =>
        {
            if (t.IsCanceled) tcs.TrySetCanceled();
            else if (t.Exception is { } ex) tcs.TrySetException(ex.InnerExceptions);
            else tcs.TrySetResult(t.Result);
        }), TaskScheduler.Default);
        return tcs.Task;
    }

    Task<T> Call<T>(string method, object? parameters = null, CancellationToken token = default) =>
        OnUi(Backend().CallAsync<T>(method, parameters, token));

    // ------------------------------------------------------------ 快照

    public async Task RefreshAsync()
    {
        try
        {
            var data = await Call<Snapshot>("snapshot");
            Apply(data, replaceEdits: true);
            Status = $"已刷新 {data.GeneratedAt}";
        }
        catch (Exception ex)
        {
            Status = ex.Message;
        }
    }

    void ScheduleSnapshotReload()
    {
        snapshotCts?.Cancel();
        var cts = snapshotCts = new CancellationTokenSource();
        _ = Task.Delay(400, cts.Token).ContinueWith(t =>
        {
            if (t.IsCanceled) return;
            dispatch(async () =>
            {
                if (cts.IsCancellationRequested || Busy) return;
                try
                {
                    Apply(await Call<Snapshot>("snapshot", token: cts.Token), replaceEdits: false);
                }
                catch (Exception)
                {
                    // 后台刷新失败保留上一次快照;下一次显式操作会暴露错误。
                }
            });
        }, TaskScheduler.Default);
    }

    void Apply(Snapshot data, bool replaceEdits)
    {
        var groupsWereDirty = GroupsDirty;
        var settingsWereDirty = SettingsDirty;
        coursesById = data.Courses.GroupBy(c => c.JxbId).ToDictionary(g => g.Key, g => g.First());
        Snapshot = data;
        SetRunning(data.Running);
        if (replaceEdits || !groupsWereDirty)
        {
            savedPlans = [.. data.Groups.Select(g => g.PlanSignature)];
            evaluations = [];
            Groups.Clear();
            foreach (var group in data.Groups) Groups.Add(group.Clone());
        }
        savedSettings = data.Settings;
        // 复制一份:界面编辑的是 Settings,savedSettings 必须保持快照原值才能判断脏标记。
        if (replaceEdits || !settingsWereDirty) Settings = data.Settings with { };
        if (SelectedGroup is null || Groups.All(g => g.Name != SelectedGroup))
            SelectedGroup = Groups.FirstOrDefault()?.Name;
        if (!data.Onboarding.Completed)
            OnboardingStep = data.Onboarding.CatalogReady ? 3 : data.Onboarding.HasAccount ? 2 : 1;
        GroupsChanged();
        Raise(nameof(Courses));
        Raise(nameof(CoursesById));
        Raise(nameof(FilteredCourses));
        Raise(nameof(StateRows));
        Raise(nameof(NeedsOnboarding));
        Raise(nameof(SettingsDirty));
        Raise(nameof(ReleaseMode));
    }

    /// 方案被编辑后调用:刷新脏标记,并请后端重新评估未保存方案的冲突。
    public void GroupsChanged()
    {
        Raise(nameof(GroupsDirty));
        Raise(nameof(SelectedGroupData));
        evaluateCts?.Cancel();
        if (!GroupsDirty || Phase != BackendPhase.Ready)
        {
            if (!GroupsDirty && evaluations.Count > 0)
            {
                evaluations = [];
                Raise(nameof(Evaluations));
            }
            return;
        }
        var cts = evaluateCts = new CancellationTokenSource();
        var payload = new
        {
            groups = Groups.Select(g => new Dictionary<string, object?>
            {
                ["name"] = g.Name,
                ["is_pe"] = g.IsPe,
                ["priority"] = g.Priority,
            }).ToList(),
        };
        _ = Task.Delay(150, cts.Token).ContinueWith(t =>
        {
            if (t.IsCanceled) return;
            dispatch(async () =>
            {
                try
                {
                    var result = await Call<GroupsEvaluateResult>("groups.evaluate", payload, cts.Token);
                    if (cts.IsCancellationRequested) return;
                    evaluations = result.Groups.GroupBy(g => g.Name).ToDictionary(g => g.Key, g => g.Last());
                    Raise(nameof(Evaluations));
                }
                catch (Exception)
                {
                }
            });
        }, TaskScheduler.Default);
    }

    // ------------------------------------------------------------ 日志

    public void ReloadLogs()
    {
        logsCts?.Cancel();
        if (Phase != BackendPhase.Ready) return;
        var cts = logsCts = new CancellationTokenSource();
        var parameters = new Dictionary<string, object?>
        {
            ["level"] = LogLevel?.ToString().ToLowerInvariant() ?? "all",
            ["query"] = LogQuery,
            ["limit"] = 800,
        };
        dispatch(async () =>
        {
            try
            {
                var result = await Call<LogsQueryResult>("logs.query", parameters, cts.Token);
                if (!cts.IsCancellationRequested) Logs = result;
            }
            catch (Exception)
            {
            }
        });
    }

    void ScheduleLogsReload()
    {
        if (Page != Page.Logs) return;
        logsCts?.Cancel();
        var cts = logsCts = new CancellationTokenSource();
        _ = Task.Delay(250, cts.Token).ContinueWith(t =>
        {
            if (!t.IsCanceled) dispatch(ReloadLogs);
        }, TaskScheduler.Default);
    }

    // ------------------------------------------------------------ 进程

    public async Task RunAsync(string task, bool adoptSiteTerm = false)
    {
        try
        {
            var parameters = new Dictionary<string, object?> { ["task"] = task, ["debug"] = Debug && !ReleaseMode };
            if (adoptSiteTerm) parameters["adopt_site_term"] = true;
            if (task == "bootstrap") BootstrapLines.Clear();
            SetRunning((await Call<RunningResult>("process.start", parameters)).Running);
        }
        catch (Exception ex)
        {
            Status = ex.Message;
        }
    }

    public async Task StopAsync(string task)
    {
        try
        {
            SetRunning((await Call<RunningResult>("process.stop", new { task })).Running);
        }
        catch (Exception ex)
        {
            Status = ex.Message;
        }
    }

    // ------------------------------------------------------------ 学期

    public Task SwitchTermAsync(string xkxnm, string xkxqm) => Perform(async () =>
    {
        var result = await Call<SwitchTermResult>("term.switch", new { xkxnm, xkxqm });
        SelectedGroup = null;
        await RefreshAsync();
        Status = MonitorRunning
            ? $"已切换到 {result.ActiveTerm}；正在运行的监控仍按原学期执行，重启监控后生效"
            : $"已切换到 {result.ActiveTerm}";
    });

    // ------------------------------------------------------------ 方案编辑

    public bool CreateGroup(string rawName)
    {
        var name = rawName.Trim();
        if (name.Length == 0 || Groups.Any(g => g.Name == name)) return false;
        Groups.Add(new PriorityGroup { Name = name });
        SelectedGroup = name;
        Status = $"已新建方案 {name}，尚未保存";
        GroupsChanged();
        return true;
    }

    public void DeleteSelectedGroup()
    {
        if (SelectedGroupData is not { } group) return;
        Groups.Remove(group);
        SelectedGroup = Groups.FirstOrDefault()?.Name;
        Status = $"已删除方案 {group.Name}，尚未保存";
        GroupsChanged();
    }

    /// 加入课程;有冲突时通过 NoticeRaised 提示(只警告,仍然加入)。
    public async Task AddCoursesAsync(IReadOnlyList<string> ids)
    {
        if (SelectedGroupData is not { } group)
        {
            Status = "请先选择或新建一个方案";
            return;
        }
        try
        {
            var result = await Call<AddCoursesResult>("groups.add_courses", new { priority = group.Priority, added = ids });
            if (result.Added.Count == 0)
            {
                Status = $"所选教学班已在“{group.Name}”中";
                return;
            }
            group.Priority = result.Priority;
            Status = $"已加入 {result.Added.Count} 个教学班到“{group.Name}”，尚未保存";
            GroupsChanged();
            if (result.Warning is { } warning) NoticeRaised?.Invoke(new Notice("时间冲突提示", warning));
        }
        catch (Exception ex)
        {
            Status = ex.Message;
        }
    }

    public void SetPriority(IEnumerable<string> priority)
    {
        if (SelectedGroupData is not { } group) return;
        group.Priority = [.. priority];
        GroupsChanged();
    }

    public void MoveMember(string id, int delta)
    {
        if (SelectedGroupData is not { } group) return;
        var index = group.Priority.IndexOf(id);
        var target = index + delta;
        if (index < 0 || target < 0 || target >= group.Priority.Count) return;
        (group.Priority[index], group.Priority[target]) = (group.Priority[target], group.Priority[index]);
        GroupsChanged();
    }

    public void RemoveMembers(IEnumerable<string> ids)
    {
        if (SelectedGroupData is not { } group) return;
        var remove = ids.ToHashSet();
        if (group.Priority.RemoveAll(remove.Contains) > 0) GroupsChanged();
    }

    public void SetPe(bool value)
    {
        if (SelectedGroupData is not { } group || group.IsPe == value) return;
        group.IsPe = value;
        GroupsChanged();
    }

    public void RevertGroups()
    {
        if (Snapshot is not { } data) return;
        savedPlans = [.. data.Groups.Select(g => g.PlanSignature)];
        Groups.Clear();
        foreach (var group in data.Groups) Groups.Add(group.Clone());
        if (Groups.All(g => g.Name != SelectedGroup)) SelectedGroup = Groups.FirstOrDefault()?.Name;
        Status = "已放弃未保存的方案修改";
        GroupsChanged();
    }

    public Task SaveGroupsAsync() => Perform(async () =>
    {
        var payload = Groups.ToDictionary(g => g.Name, g => (object)new Dictionary<string, object?>
        {
            ["is_pe"] = g.IsPe,
            ["priority"] = g.Priority,
        });
        var result = await Call<SaveGroupsResult>("groups.save", new { groups = payload });
        await RefreshAsync();
        var warnings = result.Warnings
            .Concat(result.Duplicates.Select(d => $"{Labels.ShortId(d.Key)} 重复: {string.Join(", ", d.Value)}"))
            .Concat(result.Unresolved.Select(id => $"{Labels.ShortId(id)} 无法推导查询模板"))
            .ToList();
        if (warnings.Count == 0)
        {
            Status = $"方案已保存，共监控 {result.CourseCount} 门课程";
        }
        else
        {
            Status = $"方案已保存，但有 {warnings.Count} 条提示";
            NoticeRaised?.Invoke(new Notice("方案已保存", string.Join("\n", warnings)));
        }
    });

    // ------------------------------------------------------------ 设置与引导

    public Task SaveSettingsAsync() => Perform(async () =>
    {
        await Call<OkResult>("settings.save", Settings.ToRequest());
        await RefreshAsync();
        Status = "设置已保存；正在运行的监控需重启后使用新参数";
    });

    public Task SendTestEmailAsync()
    {
        Status = "正在保存设置并发送测试邮件…";
        return Perform(async () =>
        {
            await Call<OkResult>("settings.save", Settings.ToRequest());
            var result = await Call<TestEmailResult>("settings.test_email");
            await RefreshAsync();
            Status = $"测试邮件已发送至 {result.MailTo ?? "收件人"}，请查收";
        });
    }

    public async Task SaveOnboardingAccountAsync()
    {
        if (string.IsNullOrWhiteSpace(Settings.JaccountUser))
        {
            Status = "请输入 JAccount 账号";
            return;
        }
        if (Settings.JaccountPass.Length == 0 && Settings.HasJaccountPass != true)
        {
            Status = "请输入 JAccount 密码";
            return;
        }
        await Perform(async () =>
        {
            await Call<OkResult>("settings.save", Settings.ToRequest());
            await RefreshAsync();
            OnboardingStep = 2;
            Status = "账号已安全保存；同步只会在你点击按钮后开始";
        });
    }

    public Task FinishOnboardingAsync() => Perform(async () =>
    {
        await Call<OkResult>("onboarding.complete");
        await RefreshAsync();
        Page = Page.Courses;
        Status = "初始化完成，请创建你的选课方案";
    });

    public Task SetAutoSwapAsync(bool enabled, bool dryRun) => Perform(async () =>
    {
        await Call<OkResult>("autoswap.set", new { enabled, dry_run = dryRun });
        await RefreshAsync();
        Status = "自动换课设置已保存；重启监控后生效";
    });

    async Task Perform(Func<Task> action)
    {
        Busy = true;
        try
        {
            await action();
        }
        catch (Exception ex)
        {
            Status = ex.Message;
            NoticeRaised?.Invoke(new Notice("操作失败", ex.Message));
        }
        finally
        {
            Busy = false;
        }
    }
}
