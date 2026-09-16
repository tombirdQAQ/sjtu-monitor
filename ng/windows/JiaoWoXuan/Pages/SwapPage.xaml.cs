using System.ComponentModel;
using JiaoWoXuan.Core;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace JiaoWoXuan.Pages;

public sealed class SwapGroupRow
{
    public required string Name { get; init; }
    public required string Kind { get; init; }
    public required string Held { get; init; }
    public required string Watched { get; init; }
    public required string Completed { get; init; }
    public required string Failed { get; init; }
    public Tone FailedTone { get; init; }
}

public sealed partial class SwapPage : Microsoft.UI.Xaml.Controls.Page
{
    readonly AppStore store = App.Store;
    bool rendering;

    public SwapPage()
    {
        InitializeComponent();
    }

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        store.PropertyChanged += OnStoreChanged;
        Render();
    }

    protected override void OnNavigatedFrom(NavigationEventArgs e) => store.PropertyChanged -= OnStoreChanged;

    void OnStoreChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName is nameof(AppStore.Snapshot) or nameof(AppStore.Busy) or nameof(AppStore.ReleaseMode)) Render();
    }

    void Render()
    {
        if (store.Snapshot is not { } snapshot) return;
        rendering = true;
        // 发行版不提供演练模式:隐藏第二个选项。
        if (ModeButtons.ContainerFromIndex(1) is Microsoft.UI.Xaml.UIElement dryRun)
            dryRun.Visibility = Ui.Show(!store.ReleaseMode);
        ModeButtons.SelectedIndex = (int)snapshot.Metrics.AutoSwap;
        ModeButtons.IsEnabled = !store.Busy;
        rendering = false;

        GroupRows.ItemsSource = snapshot.Groups.Select(g =>
        {
            var failed = snapshot.SwapState.Fatal.Count(g.Priority.Contains);
            return new SwapGroupRow
            {
                Name = g.Name,
                Kind = g.IsPe ? "体育" : "普通",
                Held = g.HeldLabel,
                Watched = g.WatchedCount.ToString(),
                Completed = snapshot.SwapState.Completed.Count(g.Priority.Contains).ToString(),
                Failed = g.Fatal ? "方案暂停" : failed.ToString(),
                FailedTone = g.Fatal || failed > 0 ? Tone.Danger : Tone.Neutral,
            };
        }).ToList();
        HistoryRows.ItemsSource = snapshot.SwapHistory;
        NoHistory.Visibility = Ui.Show(snapshot.SwapHistory.Count == 0);
    }

    async void OnModeChanged(object sender, SelectionChangedEventArgs e)
    {
        if (rendering || store.Snapshot is not { } snapshot || ModeButtons.SelectedIndex < 0) return;
        var mode = (AutoSwapState)ModeButtons.SelectedIndex;
        if (mode == snapshot.Metrics.AutoSwap) return;
        if (mode == AutoSwapState.Enabled
            && !await Ui.Confirm("启用真实自动换课？", "真实自动换课会执行退课和选课。换课只会向更高优先级升级，不会降级；设置在重启监控后生效。", "启用", destructive: true))
        {
            Render();
            return;
        }
        await store.SetAutoSwapAsync(mode != AutoSwapState.Off, mode == AutoSwapState.DryRun);
    }
}
