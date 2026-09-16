using JiaoWoXuan.Core;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using Microsoft.Windows.AppNotifications;
using Microsoft.Windows.AppNotifications.Builder;

namespace JiaoWoXuan;

public partial class App : Application
{
    public static AppStore Store { get; private set; } = null!;
    public static MainWindow? MainWindow { get; private set; }

    bool notificationsRegistered;

    static readonly string DiagnosticsDir = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "sjtu-monitor-ng");

    public App()
    {
        Breadcrumb("app: start", reset: true);
        UnhandledException += (_, e) => CrashLog(e.Exception);
        AppDomain.CurrentDomain.UnhandledException += (_, e) => CrashLog(e.ExceptionObject as Exception);
        TaskScheduler.UnobservedTaskException += (_, e) => CrashLog(e.Exception);
        InitializeComponent();
    }

    /// 启动阶段面包屑:原生层 fail-fast 抓不到托管异常,靠最后一条面包屑定位崩溃位置。
    public static void Breadcrumb(string step, bool reset = false)
    {
        try
        {
            Directory.CreateDirectory(DiagnosticsDir);
            var line = $"{DateTime.Now:HH:mm:ss.fff} {step}{Environment.NewLine}";
            var path = Path.Combine(DiagnosticsDir, "startup.log");
            if (reset) File.WriteAllText(path, line);
            else File.AppendAllText(path, line);
        }
        catch (Exception)
        {
        }
    }

    static void CrashLog(Exception? exception)
    {
        try
        {
            Directory.CreateDirectory(DiagnosticsDir);
            File.AppendAllText(Path.Combine(DiagnosticsDir, "crash.log"),
                $"==== {DateTime.Now:yyyy-MM-dd HH:mm:ss}{Environment.NewLine}{exception}{Environment.NewLine}");
        }
        catch (Exception)
        {
        }
    }

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        var queue = DispatcherQueue.GetForCurrentThread();
        Store = new AppStore(action =>
        {
            if (queue.HasThreadAccess) action();
            else queue.TryEnqueue(() => action());
        });
        Store.SystemNotification += ShowToast;

        Breadcrumb("app: create window");
        MainWindow = new MainWindow(Store);
        Breadcrumb("app: activate window");
        MainWindow.Activate();

        Breadcrumb("app: register notifications");
        try
        {
            AppNotificationManager.Default.Register();
            notificationsRegistered = true;
        }
        catch (Exception)
        {
            // 非打包运行且系统不支持时没有 Toast,弹窗提示仍然有效。
        }
        Breadcrumb("app: start backend");
        Store.Start();
        Breadcrumb("app: launched");
    }

    void ShowToast(Notice notice)
    {
        if (!notificationsRegistered || MainWindow?.IsForeground == true) return;
        try
        {
            var toast = new AppNotificationBuilder().AddText(notice.Title).AddText(notice.Message).BuildNotification();
            AppNotificationManager.Default.Show(toast);
        }
        catch (Exception)
        {
        }
    }

    public static void ExitApplication()
    {
        Store.Shutdown();
        try { AppNotificationManager.Default.Unregister(); } catch (Exception) { }
        Current.Exit();
    }
}
