using System.ComponentModel;
using JiaoWoXuan.Core;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace JiaoWoXuan.Pages;

public sealed partial class LogsPage : Microsoft.UI.Xaml.Controls.Page
{
    readonly AppStore store = App.Store;
    static readonly LogLevel?[] Levels = [null, LogLevel.Info, LogLevel.Warn, LogLevel.Error, LogLevel.Debug];
    bool rendering;

    public LogsPage()
    {
        InitializeComponent();
        foreach (var level in Levels) LevelBar.Items.Add(new SelectorBarItem());
    }

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        store.PropertyChanged += OnStoreChanged;
        QueryBox.Text = store.LogQuery;
        Render();
        store.ReloadLogs();
    }

    protected override void OnNavigatedFrom(NavigationEventArgs e) => store.PropertyChanged -= OnStoreChanged;

    void OnStoreChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName is nameof(AppStore.Logs)) Render();
    }

    void Render()
    {
        rendering = true;
        var counts = store.Logs.Counts;
        for (var i = 0; i < Levels.Length; i++)
        {
            var item = (SelectorBarItem)LevelBar.Items[i];
            item.Text = $"{(Levels[i] is { } level ? Labels.Of(level) : "全部")} {counts.For(Levels[i])}";
        }
        LevelBar.SelectedItem = LevelBar.Items[Array.IndexOf(Levels, store.LogLevel)];
        rendering = false;

        var entries = store.Logs.Entries;
        Entries.ItemsSource = entries;
        Empty.Visibility = Ui.Show(entries.Count == 0);
        if (FollowToggle.IsChecked == true && entries.Count > 0)
            Entries.ScrollIntoView(entries[^1]);
    }

    void OnLevelChanged(SelectorBar sender, SelectorBarSelectionChangedEventArgs args)
    {
        if (rendering) return;
        var index = sender.Items.IndexOf(sender.SelectedItem);
        if (index >= 0) store.LogLevel = Levels[index];
    }

    void OnQueryChanged(AutoSuggestBox sender, AutoSuggestBoxTextChangedEventArgs args)
    {
        if (args.Reason == AutoSuggestionBoxTextChangeReason.UserInput) store.LogQuery = sender.Text;
    }
}
