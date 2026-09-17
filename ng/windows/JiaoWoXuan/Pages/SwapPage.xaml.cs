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
        ModeButtons.SelectedIndex = (int)snapshot.Metrics.AutoSwap;
        ModeDescription.Text = snapshot.Metrics.AutoSwap switch
        {
            AutoSwapState.DryRun => "发现可以换入的更高优先级课程时只发通知，不实际退选或选课。设置在重启监控后生效。",
            AutoSwapState.Enabled => "发现更高优先级课程有空位时自动退旧选新，只升级不降级；时间冲突的课程不会被选择。设置在重启监控后生效。",
            _ => "不处理换课，只记录余量变化。设置在重启监控后生效。",
        };
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
            && !await Ui.Confirm("启用自动换课？", "启用后监控会真正执行退课和选课。换课只会向更高优先级升级，不会降级；设置在重启监控后生效。", "启用", destructive: true))
        {
            Render();
            return;
        }
        await store.SetAutoSwapAsync(mode != AutoSwapState.Off, mode == AutoSwapState.DryRun);
    }
}
