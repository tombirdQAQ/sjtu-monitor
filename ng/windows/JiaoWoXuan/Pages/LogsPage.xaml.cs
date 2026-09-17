using System.ComponentModel;
using JiaoWoXuan.Core;
using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Navigation;

namespace JiaoWoXuan.Pages;

public sealed class LogRowItem(LogEntry entry)
{
    public LogEntry Entry { get; } = entry;
    public string LevelGlyph => LogsPage.Glyph(Entry.Level);
    public Brush LevelForeground => Ui.ToneForeground(Entry.LevelTone);
    public Brush LevelBackground => Ui.ToneBackground(Entry.LevelTone);

    public Brush RowBackground => Entry.Level switch
    {
        LogLevel.Error => new SolidColorBrush(Windows.UI.Color.FromArgb(0x1F, 0xE0, 0x40, 0x40)),
        LogLevel.Warn => new SolidColorBrush(Windows.UI.Color.FromArgb(0x14, 0xF0, 0x9A, 0x20)),
        _ => new SolidColorBrush(Colors.Transparent),
    };

    public Brush MessageForeground => Entry.Level == LogLevel.Error
        ? Ui.ToneForeground(Tone.Danger)
        : (Brush)Application.Current.Resources["TextFillColorPrimaryBrush"];
}

public sealed partial class LogsPage : Microsoft.UI.Xaml.Controls.Page
{
    readonly AppStore store = App.Store;
    static readonly LogLevel?[] Levels = [null, LogLevel.Info, LogLevel.Warn, LogLevel.Error, LogLevel.Debug];

    public LogsPage()
    {
        InitializeComponent();
    }

    public static string Glyph(LogLevel? level) => level switch
    {
        LogLevel.Info => "",
        LogLevel.Warn => "",
        LogLevel.Error => "",
        LogLevel.Debug => "",
        _ => "",
    };

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
        if (e.PropertyName is nameof(AppStore.Logs) or nameof(AppStore.LogLevel)) Render();
    }

    void Render()
    {
        RenderLevelCards();
        var entries = store.Logs.Entries.Select(entry => new LogRowItem(entry)).ToList();
        Entries.ItemsSource = entries;
        Empty.Visibility = Ui.Show(entries.Count == 0);
        EmptyText.Text = store.LogLevel is null && string.IsNullOrEmpty(store.LogQuery) ? "暂无日志" : "没有符合条件的日志";
        if (FollowToggle.IsChecked == true && entries.Count > 0)
            Entries.ScrollIntoView(entries[^1]);
    }

    void RenderLevelCards()
    {
        var counts = store.Logs.Counts;
        LevelCards.Children.Clear();
        LevelCards.ColumnDefinitions.Clear();
        for (var i = 0; i < Levels.Length; i++)
        {
            var level = Levels[i];
            var tone = level switch
            {
                null => Tone.Accent,
                LogLevel.Warn => Tone.Warning,
                LogLevel.Error => Tone.Danger,
                LogLevel.Debug => Tone.Neutral,
                _ => Tone.Accent,
            };
            var selected = store.LogLevel == level;
            LevelCards.ColumnDefinitions.Add(new ColumnDefinition());

            var circle = new Border
            {
                Width = 32,
                Height = 32,
                CornerRadius = new CornerRadius(16),
                Background = selected ? Ui.ToneForeground(tone) : Ui.ToneBackground(tone),
                Child = new FontIcon
                {
                    Glyph = Glyph(level),
                    FontSize = 15,
                    Foreground = selected ? new SolidColorBrush(Colors.White) : Ui.ToneForeground(tone),
                },
            };
            var text = new StackPanel
            {
                VerticalAlignment = VerticalAlignment.Center,
                Children =
                {
                    new TextBlock { Text = counts.For(level).ToString(), FontSize = 20, FontWeight = Microsoft.UI.Text.FontWeights.SemiBold },
                    new TextBlock { Text = level is { } l ? Labels.Of(l) : "全部", Style = (Style)Application.Current.Resources["SecondaryText"] },
                },
            };
            var content = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 12, Children = { circle, text } };
            var button = new Button
            {
                Content = content,
                Style = (Style)Application.Current.Resources["GlassCardButton"],
                CornerRadius = new CornerRadius(16),
                Padding = new Thickness(12, 9, 12, 9),
            };
            if (selected)
            {
                button.BorderBrush = Ui.ToneForeground(tone);
            }
            var captured = level;
            button.Click += (_, _) => store.LogLevel = store.LogLevel == captured && captured is not null ? null : captured;
            Grid.SetColumn(button, i);
            LevelCards.Children.Add(button);
        }
    }

    void OnQueryChanged(AutoSuggestBox sender, AutoSuggestBoxTextChangedEventArgs args)
    {
        if (args.Reason == AutoSuggestionBoxTextChangeReason.UserInput) store.LogQuery = sender.Text;
    }
}
