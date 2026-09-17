using System.ComponentModel;
using System.Windows.Input;
using JiaoWoXuan.Core;
using JiaoWoXuan.Pages;
using Microsoft.UI;
using Microsoft.UI.Input;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using Windows.System;
using CorePage = JiaoWoXuan.Core.Page;

namespace JiaoWoXuan;

public sealed partial class MainWindow : Window
{
    readonly AppStore store;
    readonly Queue<Notice> pendingNotices = new();
    bool showingNotice;
    bool exiting;
    bool syncingNavigation;

    public ICommand ShowWindowCommand { get; }
    public ICommand RunOnceCommand { get; }
    public ICommand ToggleMonitorCommand { get; }
    public ICommand ExitCommand { get; }

    public bool IsForeground { get; private set; }

    public MainWindow(AppStore store)
    {
        App.Breadcrumb("window: ctor");
        this.store = store;
        ShowWindowCommand = new RelayCommand(ShowAndActivate);
        RunOnceCommand = new RelayCommand(() => _ = store.RunAsync("once"));
        ToggleMonitorCommand = new RelayCommand(ToggleMonitor);
        ExitCommand = new RelayCommand(() => _ = RequestExitAsync());
        App.Breadcrumb("window: xaml");
        InitializeComponent();

        App.Breadcrumb("window: chrome");
        ExtendsContentIntoTitleBar = true;
        SetTitleBar(AppTitleBar);
        AppWindow.TitleBar.PreferredHeightOption = TitleBarHeightOption.Tall;
        AppWindow.SetIcon(Path.Combine(AppContext.BaseDirectory, "Assets", "AppIcon.ico"));
        SystemBackdrop = new MicaBackdrop();
        AppWindow.Resize(new Windows.Graphics.SizeInt32(1360, 880));
        if (AppWindow.Presenter is OverlappedPresenter presenter)
        {
            presenter.PreferredMinimumWidth = 1000;
            presenter.PreferredMinimumHeight = 660;
        }
        UiSettings.ApplyTheme(Root);
        NativeTheme.ApplyMenuTheme(UiSettings.Theme);
        App.Breadcrumb("window: input");

        AppWindow.Closing += OnClosing;
        Activated += (_, e) => IsForeground = e.WindowActivationState != WindowActivationState.Deactivated;
        Root.KeyboardAccelerators.Add(Accelerator(VirtualKey.S, VirtualKeyModifiers.Control, () => { if (store.GroupsDirty) _ = store.SaveGroupsAsync(); }));
        Root.KeyboardAccelerators.Add(Accelerator(VirtualKey.F5, VirtualKeyModifiers.None, () => _ = store.RefreshAsync()));
        Root.KeyboardAccelerators.Add(Accelerator(VirtualKey.O, VirtualKeyModifiers.Control | VirtualKeyModifiers.Shift, () => _ = store.RunAsync("once")));
        Root.KeyboardAccelerators.Add(Accelerator(VirtualKey.M, VirtualKeyModifiers.Control | VirtualKeyModifiers.Shift, ToggleMonitor));
        for (var i = 0; i < 5; i++)
        {
            var page = (CorePage)i;
            Root.KeyboardAccelerators.Add(Accelerator(VirtualKey.Number1 + i, VirtualKeyModifiers.Control, () => store.Page = page));
        }

        App.Breadcrumb("window: bind store");
        store.PropertyChanged += OnStoreChanged;
        store.NoticeRaised += notice => { pendingNotices.Enqueue(notice); _ = DrainNoticesAsync(); };
        Render();
        Navigate(CorePage.Overview);
        App.Breadcrumb("window: ready");
    }

    static KeyboardAccelerator Accelerator(VirtualKey key, VirtualKeyModifiers modifiers, Action action)
    {
        var accelerator = new KeyboardAccelerator { Key = key, Modifiers = modifiers };
        accelerator.Invoked += (_, e) =>
        {
            action();
            e.Handled = true;
        };
        return accelerator;
    }

    void OnStoreChanged(object? sender, PropertyChangedEventArgs e)
    {
        switch (e.PropertyName)
        {
            case nameof(AppStore.Page):
                Navigate(store.Page);
                break;
            case nameof(AppStore.Phase) or nameof(AppStore.Snapshot) or nameof(AppStore.NeedsOnboarding)
                or nameof(AppStore.Running) or nameof(AppStore.MonitorRunning) or nameof(AppStore.Status)
                or nameof(AppStore.GroupsDirty) or nameof(AppStore.Failure):
                Render();
                break;
        }
    }

    void Render()
    {
        var phase = store.Phase;
        StartingText.Visibility = phase == BackendPhase.Starting || (phase == BackendPhase.Ready && store.Snapshot is null)
            ? Visibility.Visible : Visibility.Collapsed;
        FailurePanel.Visibility = phase == BackendPhase.Failed ? Visibility.Visible : Visibility.Collapsed;
        FailureText.Text = store.Failure;

        var ready = phase == BackendPhase.Ready && store.Snapshot is not null;
        var onboarding = ready && store.NeedsOnboarding;
        OnboardingFrame.Visibility = onboarding ? Visibility.Visible : Visibility.Collapsed;
        if (onboarding && OnboardingFrame.Content is not OnboardingPage) OnboardingFrame.Navigate(typeof(OnboardingPage));
        Nav.Visibility = ready && !onboarding ? Visibility.Visible : Visibility.Collapsed;

        var monitor = store.MonitorRunning;
        var once = store.Running.Contains("once");
        var stateText = monitor ? "持续监控中" : once ? "单次检查中" : "监控未运行";
        var tone = monitor ? Tone.Success : once ? Tone.Accent : Tone.Neutral;
        MonitorStateText.Text = stateText;
        MonitorStateBackground.Fill = Ui.ToneBackground(tone);
        MonitorStateIcon.Foreground = Ui.ToneForeground(tone);
        MonitorStateIcon.Glyph = monitor ? "\uE9D9" : once ? "\uE895" : "\uE769";
        TermText.Text = store.Snapshot?.User.Term ?? "";
        OnceButton.IsEnabled = !once && store.IsReady;
        MonitorButtonText.Text = monitor ? "停止监控" : "开始监控";
        MonitorButtonIcon.Glyph = monitor ? "\uE71A" : "\uE768";
        MonitorButton.Style = (Style)Application.Current.Resources[monitor ? "DefaultButtonStyle" : "AccentButtonStyle"];
        MonitorButton.IsEnabled = store.IsReady;
        TaskProgress.Visibility = store.Running.Except(["monitor"]).Any() ? Visibility.Visible : Visibility.Collapsed;

        TitleStatus.Text = store.GroupsDirty ? "● 方案有未保存的修改" : store.Status;
        CoursesNavItem.Content = store.GroupsDirty ? "课程方案 ●" : "课程方案";
        TrayStatusItem.Text = stateText;
        TrayMonitorItem.Text = monitor ? "停止持续监控" : "开始持续监控";
        TrayIcon.ToolTipText = $"交我选 · {stateText}";
    }

    void Navigate(CorePage page)
    {
        var type = page switch
        {
            CorePage.Courses => typeof(CoursesPage),
            CorePage.Swap => typeof(SwapPage),
            CorePage.Snapshot => typeof(SnapshotPage),
            CorePage.Logs => typeof(LogsPage),
            CorePage.Settings => typeof(SettingsPage),
            _ => typeof(OverviewPage),
        };
        // 系统默认的入场过渡;页面启用缓存,来回切换不重建、不闪烁。
        if (ContentFrame.Content?.GetType() != type)
            ContentFrame.Navigate(type, null, new Microsoft.UI.Xaml.Media.Animation.EntranceNavigationTransitionInfo());
        syncingNavigation = true;
        Nav.SelectedItem = page == CorePage.Settings
            ? Nav.SettingsItem
            : Nav.MenuItems.OfType<NavigationViewItem>().FirstOrDefault(item => (string)item.Tag == page.ToString());
        Nav.Header = null;
        syncingNavigation = false;
    }

    void OnNavigationChanged(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
    {
        if (syncingNavigation) return;
        if (args.IsSettingsSelected)
            store.Page = CorePage.Settings;
        else if (args.SelectedItem is NavigationViewItem { Tag: string tag } && Enum.TryParse<CorePage>(tag, out var page))
            store.Page = page;
    }

    // 侧栏收起为图标条时,底部的监控状态与按钮放不下,隐藏;展开时再显示。
    void OnPaneOpening(NavigationView sender, object args) => PaneFooterPanel.Visibility = Visibility.Visible;

    void OnPaneClosing(NavigationView sender, NavigationViewPaneClosingEventArgs args) =>
        PaneFooterPanel.Visibility = sender.DisplayMode == NavigationViewDisplayMode.Minimal ? Visibility.Visible : Visibility.Collapsed;

    void OnDisplayModeChanged(NavigationView sender, NavigationViewDisplayModeChangedEventArgs args) =>
        PaneFooterPanel.Visibility = sender.IsPaneOpen ? Visibility.Visible : Visibility.Collapsed;

    void OnRunOnce(object sender, RoutedEventArgs e) => _ = store.RunAsync("once");

    void OnToggleMonitor(object sender, RoutedEventArgs e) => ToggleMonitor();

    void ToggleMonitor()
    {
        if (!store.IsReady) return;
        _ = store.MonitorRunning ? store.StopAsync("monitor") : store.RunAsync("monitor");
    }

    void OnRefresh(object sender, RoutedEventArgs e) => _ = store.RefreshAsync();

    void OnRestartBackend(object sender, RoutedEventArgs e) => store.RestartBackend();

    void ShowAndActivate()
    {
        AppWindow.Show();
        Activate();
    }

    /// 关窗 = 隐藏到托盘,监控继续运行;真正退出走托盘菜单。
    void OnClosing(AppWindow sender, AppWindowClosingEventArgs args)
    {
        if (exiting) return;
        args.Cancel = true;
        AppWindow.Hide();
        if (!UiSettings.TrayHintShown)
        {
            UiSettings.TrayHintShown = true;
            TrayIcon.ShowNotification("交我选仍在后台运行", "监控继续在通知区域运行；右键托盘图标可退出。");
        }
    }

    async Task RequestExitAsync()
    {
        var reasons = new List<string>();
        if (store.GroupsDirty) reasons.Add("选课方案还有未保存的修改，退出后将丢失。");
        if (store.MonitorRunning) reasons.Add("持续监控正在运行，退出会停止监控。");
        if (reasons.Count > 0)
        {
            ShowAndActivate();
            var dialog = new ContentDialog
            {
                XamlRoot = Root.XamlRoot,
                Title = "确定退出交我选？",
                Content = string.Join("\n", reasons),
                PrimaryButtonText = "退出",
                CloseButtonText = "取消",
                DefaultButton = ContentDialogButton.Close,
            };
            if (await dialog.ShowAsync() != ContentDialogResult.Primary) return;
        }
        exiting = true;
        TrayIcon.Dispose();
        App.ExitApplication();
    }

    async Task DrainNoticesAsync()
    {
        if (showingNotice || Root.XamlRoot is null) return;
        showingNotice = true;
        try
        {
            while (pendingNotices.TryDequeue(out var notice))
            {
                var dialog = new ContentDialog
                {
                    XamlRoot = Root.XamlRoot,
                    Title = notice.Title,
                    Content = new ScrollViewer
                    {
                        MaxHeight = 360,
                        Content = new TextBlock { Text = notice.Message, TextWrapping = TextWrapping.Wrap, IsTextSelectionEnabled = true },
                    },
                    CloseButtonText = "好",
                    DefaultButton = ContentDialogButton.Close,
                };
                try
                {
                    await dialog.ShowAsync();
                }
                catch (Exception)
                {
                    // 已有其他 ContentDialog 打开(例如确认框),稍后重试。
                    pendingNotices.Enqueue(notice);
                    await Task.Delay(500);
                }
            }
        }
        finally
        {
            showingNotice = false;
        }
    }

    /// 供页面弹确认框。
    public async Task<bool> ConfirmAsync(string title, string message, string primary, bool destructive = false)
    {
        var dialog = new ContentDialog
        {
            XamlRoot = Root.XamlRoot,
            Title = title,
            Content = message,
            PrimaryButtonText = primary,
            CloseButtonText = "取消",
            DefaultButton = destructive ? ContentDialogButton.Close : ContentDialogButton.Primary,
        };
        return await dialog.ShowAsync() == ContentDialogResult.Primary;
    }
}

public sealed class RelayCommand(Action execute) : ICommand
{
    public event EventHandler? CanExecuteChanged { add { } remove { } }
    public bool CanExecute(object? parameter) => true;
    public void Execute(object? parameter) => execute();
}
