using System.ComponentModel;
using JiaoWoXuan.Core;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace JiaoWoXuan.Pages;

public sealed partial class OverviewPage : Microsoft.UI.Xaml.Controls.Page
{
    readonly AppStore store = App.Store;

    public OverviewPage()
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
        if (e.PropertyName is nameof(AppStore.Snapshot) or nameof(AppStore.Running) or nameof(AppStore.MonitorRunning))
            Render();
    }

    void Render()
    {
        if (store.Snapshot is not { } snapshot) return;
        UserName.Text = Labels.UserValue(snapshot.User.Name);
        UserTerm.Text = $"{snapshot.User.Term} · {Labels.UserValue(snapshot.User.Major)}";
        GeneratedAt.Text = $"更新于 {snapshot.GeneratedAt}";

        var monitor = store.MonitorRunning;
        var once = store.Running.Contains("once");
        MonitorTitle.Text = monitor ? "持续监控中" : once ? "单次检查中" : "未运行";
        MonitorSubtitle.Text = monitor ? "正在按配置轮询课程余量" : once ? "正在执行一次本地监控流程" : "可以启动单次检查或持续监控";
        MonitorIcon.Foreground = Ui.ToneForeground(monitor ? Tone.Success : once ? Tone.Accent : Tone.Neutral);
        IntervalText.Text = snapshot.Metrics.Interval;
        AutoSwapBadge.Text = Labels.Of(snapshot.Metrics.AutoSwap);
        AutoSwapBadge.Tone = ToneOf(snapshot.Metrics.AutoSwap);
        OnceButton.Content = once ? "检查中…" : "单次检查";
        OnceButton.IsEnabled = !once;
        MonitorButton.Content = monitor ? "停止监控" : "开始持续监控";
        MonitorButton.Style = (Style)Application.Current.Resources[monitor ? "DefaultButtonStyle" : "AccentButtonStyle"];

        RenderMetrics(snapshot.Metrics);
        RenderProfile(snapshot);
        RenderGroups(snapshot);
    }

    static Tone ToneOf(AutoSwapState state) => state switch
    {
        AutoSwapState.Enabled => Tone.Danger,
        AutoSwapState.DryRun => Tone.Accent,
        _ => Tone.Neutral,
    };

    void RenderMetrics(Metrics metrics)
    {
        var items = new (string Title, string Value, Tone Tone)[]
        {
            ("查询课程", metrics.Queries.ToString(), Tone.Neutral),
            ("方案组", metrics.Groups.ToString(), Tone.Neutral),
            ("快照教学班", metrics.Snapshot.ToString(), Tone.Neutral),
            ("当前目标", metrics.Watched.ToString(), Tone.Neutral),
            ("目录空位", metrics.OpenCourses.ToString(), Tone.Neutral),
            ("自动换课", Labels.Of(metrics.AutoSwap), ToneOf(metrics.AutoSwap)),
        };
        MetricsGrid.Children.Clear();
        MetricsGrid.ColumnDefinitions.Clear();
        for (var i = 0; i < items.Length; i++)
        {
            MetricsGrid.ColumnDefinitions.Add(new ColumnDefinition());
            var value = new TextBlock { Text = items[i].Value, Style = (Style)Application.Current.Resources["SubtitleTextBlockStyle"] };
            if (items[i].Tone != Tone.Neutral) value.Foreground = Ui.ToneForeground(items[i].Tone);
            var card = new Border
            {
                Style = (Style)Application.Current.Resources["CardBorder"],
                Padding = new Thickness(14, 10, 14, 12),
                Child = new StackPanel
                {
                    Spacing = 4,
                    Children =
                    {
                        new TextBlock { Text = items[i].Title, Style = (Style)Application.Current.Resources["SecondaryText"] },
                        value,
                    },
                },
            };
            Grid.SetColumn(card, i);
            MetricsGrid.Children.Add(card);
        }
    }

    void RenderProfile(Snapshot snapshot)
    {
        var rows = new (string, string)[]
        {
            ("姓名", Labels.UserValue(snapshot.User.Name)),
            ("学号", Labels.UserValue(snapshot.User.StudentId)),
            ("班级", Labels.UserValue(snapshot.User.ClassName)),
            ("专业", Labels.UserValue(snapshot.User.Major)),
            ("学期", snapshot.User.Term),
            ("目录更新", snapshot.User.CatalogFetchedAt ?? "-"),
            ("已选同步", snapshot.ChoosedAt ?? "-"),
        };
        ProfileGrid.Children.Clear();
        ProfileGrid.RowDefinitions.Clear();
        ProfileGrid.ColumnDefinitions.Clear();
        ProfileGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        ProfileGrid.ColumnDefinitions.Add(new ColumnDefinition());
        for (var i = 0; i < rows.Length; i++)
        {
            ProfileGrid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            var label = new TextBlock { Text = rows[i].Item1, Style = (Style)Application.Current.Resources["SecondaryText"] };
            var value = new TextBlock { Text = rows[i].Item2, IsTextSelectionEnabled = true };
            Grid.SetRow(label, i);
            Grid.SetRow(value, i);
            Grid.SetColumn(value, 1);
            ProfileGrid.Children.Add(label);
            ProfileGrid.Children.Add(value);
        }
    }

    void RenderGroups(Snapshot snapshot)
    {
        GroupList.Children.Clear();
        NoGroups.Visibility = Ui.Show(snapshot.Groups.Count == 0);
        foreach (var group in snapshot.Groups)
        {
            var badges = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 6, VerticalAlignment = VerticalAlignment.Center };
            if (group.ConflictCount > 0) badges.Children.Add(Ui.Badge($"冲突 {group.ConflictCount}", Tone.Danger));
            if (group.Fatal) badges.Children.Add(Ui.Badge("暂停", Tone.Danger));
            var grid = new Grid { ColumnSpacing = 8 };
            grid.ColumnDefinitions.Add(new ColumnDefinition());
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            grid.Children.Add(new StackPanel
            {
                Children =
                {
                    new TextBlock { Text = group.Name, Style = (Style)Application.Current.Resources["BodyStrongTextBlockStyle"] },
                    new TextBlock { Text = $"{group.HeldLabel} · 监控 {group.WatchedCount}", Style = (Style)Application.Current.Resources["SecondaryText"] },
                },
            });
            Grid.SetColumn(badges, 1);
            grid.Children.Add(badges);
            var name = group.Name;
            var button = new Button
            {
                Content = grid,
                HorizontalAlignment = HorizontalAlignment.Stretch,
                HorizontalContentAlignment = HorizontalAlignment.Stretch,
                Background = null,
                BorderThickness = new Thickness(0),
                Padding = new Thickness(8, 6, 8, 6),
            };
            button.Click += (_, _) =>
            {
                store.SelectedGroup = name;
                store.Page = Core.Page.Courses;
            };
            GroupList.Children.Add(button);
        }
    }

    void OnRunOnce(object sender, RoutedEventArgs e) => _ = store.RunAsync("once");

    void OnToggleMonitor(object sender, RoutedEventArgs e) =>
        _ = store.MonitorRunning ? store.StopAsync("monitor") : store.RunAsync("monitor");
}
