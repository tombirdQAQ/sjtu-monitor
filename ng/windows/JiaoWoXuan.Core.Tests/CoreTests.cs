using System.Collections.Concurrent;
using System.Text.Json;
using JiaoWoXuan.Core;
using Xunit;

namespace JiaoWoXuan.Core.Tests;

public class ModelDecodingTests
{
    [Fact]
    public void GroupConflictsKeepRawDictionaryKeys()
    {
        const string json = """
            {"name":"物理","is_pe":false,"priority":["A1_b2","held"],"held":"held","held_label":"大学物理 - 02",
             "watched_count":1,"fatal":false,"members":[],
             "conflicts":{"A1_b2":{"status":"conflict","with":"高数 - 01","detail":"周一 第2节 (第1周)"}},
             "conflict_count":1}
            """;
        var group = JsonSerializer.Deserialize<PriorityGroup>(json, Json.Options)!;
        Assert.True(group.Conflicts["A1_b2"].IsConflict);
        Assert.Equal("与已选 高数 - 01 冲突：周一 第2节 (第1周)", group.Conflicts["A1_b2"].Note);
        Assert.Equal(group.PlanSignature, group.Clone().PlanSignature);
    }

    [Fact]
    public void SnakeCaseEnumsDecode()
    {
        var metrics = JsonSerializer.Deserialize<Metrics>(
            """{"queries":1,"groups":1,"snapshot":1,"watched":1,"open_courses":2,"interval":"60-120s","auto_swap":"dry_run"}""",
            Json.Options)!;
        Assert.Equal(AutoSwapState.DryRun, metrics.AutoSwap);
        var rating = JsonSerializer.Deserialize<CourseRating>(
            """{"status":"teacher_unrated","score":0,"count":0}""", Json.Options)!;
        Assert.Equal(RatingStatus.TeacherUnrated, rating.Status);
        Assert.Equal(0, rating.Score);
        Assert.Null(rating.SortScore);
    }

    [Fact]
    public void BootstrapResultSiteTermLabel()
    {
        var exit = JsonSerializer.Deserialize<ProcessExit>(
            """{"task":"detect-term","code":0,"stopped":false,"result":{"ok":true,"site_term":{"label":"2026-2027 秋"}}}""",
            Json.Options)!;
        Assert.Equal("2026-2027 秋", exit.Result!.SiteTermLabel);
    }
}

public class CourseFilterTests
{
    static CourseRow Course(string id, string title, double? score = null, bool open = false, string? group = null) => new()
    {
        JxbId = id,
        Title = title,
        SearchText = $"{title} {id}".ToLowerInvariant(),
        Availability = open ? Availability.Open : Availability.Full,
        Group = group,
        Rating = new CourseRating { Status = score is null ? RatingStatus.Unknown : RatingStatus.Rated, Score = score },
    };

    [Fact]
    public void RatingSortPutsUnratedLast()
    {
        var result = new CourseFilter()
            .Apply([Course("a", "甲"), Course("b", "乙", 3), Course("c", "丙", 4.5)], new CourseSortOrder(CourseColumn.Rating, Descending: true));
        Assert.Equal(["c", "b", "a"], result.Select(c => c.JxbId));
    }

    [Fact]
    public void HeaderClickCyclesAscendingDescendingOff()
    {
        var sort = new CourseSortOrder().Toggle(CourseColumn.Title);
        Assert.Equal(new CourseSortOrder(CourseColumn.Title), sort);
        sort = sort.Toggle(CourseColumn.Title);
        Assert.True(sort.Descending);
        Assert.Null(sort.Toggle(CourseColumn.Title).Column);
        Assert.Equal(new CourseSortOrder(CourseColumn.Rating), sort.Toggle(CourseColumn.Rating));
    }

    [Fact]
    public void FiltersCombine()
    {
        var result = new CourseFilter { OnlyOpen = true, OnlyUnassigned = true, Query = "物理" }.Apply([
            Course("a", "大学物理", open: true),
            Course("b", "大学物理", open: true, group: "g"),
            Course("c", "大学物理"),
            Course("d", "高等数学", open: true),
        ]);
        Assert.Equal(["a"], result.Select(c => c.JxbId));
    }
}

/// 真正起一个 ng_service(需要仓库里的 conda Python),驱动 AppStore 走一遍主要流程。
public sealed class ServiceIntegrationTests : IDisposable
{
    readonly string dataDir = Path.Combine(Path.GetTempPath(), "ng-test-" + Guid.NewGuid().ToString("N"));
    readonly BlockingCollection<Action> uiQueue = new();
    readonly Thread uiThread;

    public ServiceIntegrationTests()
    {
        Directory.CreateDirectory(dataDir);
        uiThread = new Thread(() =>
        {
            SynchronizationContext.SetSynchronizationContext(new QueueContext(uiQueue));
            foreach (var action in uiQueue.GetConsumingEnumerable()) action();
        }) { IsBackground = true };
        uiThread.Start();
    }

    public void Dispose()
    {
        uiQueue.CompleteAdding();
        try { Directory.Delete(dataDir, recursive: true); } catch (IOException) { }
    }

    sealed class QueueContext(BlockingCollection<Action> queue) : SynchronizationContext
    {
        public override void Post(SendOrPostCallback d, object? state)
        {
            if (!queue.IsAddingCompleted) queue.Add(() => d(state));
        }
    }

    static string? RepoRoot()
    {
        for (var dir = new DirectoryInfo(AppContext.BaseDirectory); dir is not null; dir = dir.Parent)
            if (File.Exists(Path.Combine(dir.FullName, "ng_service.py"))) return dir.FullName;
        return null;
    }

    Task<T> OnUi<T>(Func<Task<T>> func)
    {
        var tcs = new TaskCompletionSource<T>(TaskCreationOptions.RunContinuationsAsynchronously);
        uiQueue.Add(async () =>
        {
            try { tcs.SetResult(await func()); }
            catch (Exception ex) { tcs.SetException(ex); }
        });
        return tcs.Task;
    }

    static async Task WaitUntil(Func<bool> condition, int timeoutMs = 30_000)
    {
        var deadline = DateTime.UtcNow.AddMilliseconds(timeoutMs);
        while (!condition())
        {
            if (DateTime.UtcNow > deadline) throw new TimeoutException();
            await Task.Delay(50);
        }
    }

    [Fact]
    public async Task StoreDrivesRealService()
    {
        var root = RepoRoot();
        if (root is null) return; // 仓库外运行

        var term = Path.Combine(dataDir, "terms", "2026-3");
        Directory.CreateDirectory(term);
        File.WriteAllText(Path.Combine(dataDir, "user_settings.json"), """
            {"term":{"xkxnm":"2026","xkxqm":"3"},
             "terms":{"2026-3":{"priority_groups":{"物理":{"is_pe":false,"priority":["a","held"]}}}}}
            """);
        File.WriteAllText(Path.Combine(term, "catalog.json"), """
            {"courses":[{"kch":"PHY1","kcmc":"大学物理","kch_id":"K1","kklxdm":"01","classes":[
               {"jxb_id":"a","jxbmc":"物理-01","sksj":"星期一第2-3节{1-8周}"},
               {"jxb_id":"held","jxbmc":"物理-02","sksj":"星期二第1-2节{1-16周}"},
               {"jxb_id":"b","jxbmc":"物理-03","sksj":"星期一第1-2节{1-16周}"}]}],
             "choosed":[
               {"jxb_id":"held","kcmc":"大学物理","jxbmc":"物理-02","sksj":"星期二第1-2节{1-16周}"},
               {"jxb_id":"x","kcmc":"高等数学","jxbmc":"数学-01","sksj":"星期一第1-2节{1-16周}"}]}
            """);

        var env = System.Environment.GetEnvironmentVariables().Cast<System.Collections.DictionaryEntry>()
            .ToDictionary(e => (string)e.Key, e => (string?)e.Value ?? "", StringComparer.OrdinalIgnoreCase);
        env["SJTU_MONITOR_ROOT"] = root;
        BackendLaunch launch;
        try
        {
            launch = BackendLocator.Resolve(env);
        }
        catch (BackendException) when (!env.ContainsKey("SJTU_MONITOR_PYTHON"))
        {
            return; // 没有可用的 Python;显式设置了 SJTU_MONITOR_PYTHON 时必须真正跑起来
        }
        var launchEnv = new Dictionary<string, string>(launch.Environment) { ["SJTU_MONITOR_DATA_DIR"] = dataDir };
        launch = launch with { Environment = launchEnv };

        var notices = new ConcurrentQueue<Notice>();
        var store = new AppStore(action => uiQueue.Add(action), () => launch);
        store.NoticeRaised += notices.Enqueue;
        uiQueue.Add(store.Start);
        try
        {
            await WaitUntil(() => store.Snapshot is not null || store.Phase == BackendPhase.Failed);
            Assert.True(store.Phase == BackendPhase.Ready, store.Failure);
            Assert.Equal(BackendPhase.Ready, store.Phase);
            Assert.Equal("物理", store.SelectedGroup);
            Assert.Equal(1, store.Groups[0].ConflictCount);
            Assert.False(store.GroupsDirty);

            await OnUi(async () => { await store.AddCoursesAsync(["b"]); return true; });
            Assert.Equal(["a", "b", "held"], store.Groups[0].Priority);
            Assert.True(store.GroupsDirty);
            Assert.Contains(notices, n => n.Title == "时间冲突提示");
            await WaitUntil(() => store.Evaluations.TryGetValue("物理", out var e) && e.ConflictCount == 2);

            await OnUi(async () => { await store.SaveGroupsAsync(); return true; });
            Assert.False(store.GroupsDirty);
            Assert.Contains("\"b\"", File.ReadAllText(Path.Combine(dataDir, "user_settings.json")));

            await OnUi(async () => { await store.RunAsync("no-such-task"); return true; });
            Assert.Contains("未知任务", store.Status);

            await OnUi(async () => { await store.EnterDemoAsync(); return true; });
            Assert.True(store.DemoMode);
            Assert.Contains(store.Courses, c => c.JxbId.StartsWith("DEMO-"));
            await OnUi(async () => { await store.RunAsync("monitor"); return true; });
            Assert.Contains("演示模式", store.Status);
            await OnUi(async () => { await store.ExitDemoAsync(); return true; });
            Assert.False(store.DemoMode);
            Assert.Equal("物理", store.Groups[0].Name);
        }
        finally
        {
            store.Shutdown();
        }
    }
}
