using System.Collections.ObjectModel;
using System.ComponentModel;
using JiaoWoXuan.Core;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Navigation;
using Windows.System;

namespace JiaoWoXuan.Pages;

public sealed class GroupTab(PriorityGroup group, string caption, int conflicts)
{
    public string Name { get; } = group.Name;
    public string Caption { get; } = caption;
    public string ConflictText { get; } = conflicts > 0 ? $"冲突 {conflicts}" : "";
    public string FatalText { get; } = group.Fatal ? "暂停" : "";
}

public sealed class PriorityItem
{
    public required string Id { get; init; }
    public required string Index { get; init; }
    public required string Title { get; init; }
    public required string Summary { get; init; }
    public string Note { get; init; } = "";
    public Visibility NoteVisibility => Ui.ShowText(Note);
    public string BadgeText { get; init; } = "";
    public Tone BadgeTone { get; init; }
}

public sealed partial class CoursesPage : Microsoft.UI.Xaml.Controls.Page
{
    readonly AppStore store = App.Store;
    readonly ObservableCollection<PriorityItem> priorityItems = [];
    bool rendering;
    string? inspected;
    CancellationTokenSource? searchDebounce;

    public CoursesPage()
    {
        InitializeComponent();
        NavigationCacheMode = NavigationCacheMode.Required;
        PriorityList.ItemsSource = priorityItems;
    }

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        store.PropertyChanged += OnStoreChanged;
        RenderAll();
    }

    protected override void OnNavigatedFrom(NavigationEventArgs e) => store.PropertyChanged -= OnStoreChanged;

    void OnStoreChanged(object? sender, PropertyChangedEventArgs e)
    {
        switch (e.PropertyName)
        {
            case nameof(AppStore.Snapshot):
                RenderAll();
                break;
            case nameof(AppStore.FilteredCourses) or nameof(AppStore.CourseFilter):
                RenderCourses();
                break;
            case nameof(AppStore.GroupsDirty) or nameof(AppStore.SelectedGroup) or nameof(AppStore.SelectedGroupData)
                or nameof(AppStore.Evaluations) or nameof(AppStore.Busy):
                RenderPlan();
                break;
            case nameof(AppStore.Running):
                RenderToolbar();
                break;
        }
    }

    void RenderAll()
    {
        RenderTerm();
        RenderToolbar();
        RenderCourses();
        RenderPlan();
        RenderInspector();
    }

    // ------------------------------------------------------------ 学期

    void RenderTerm()
    {
        if (store.Snapshot is not { } snapshot) return;
        var active = snapshot.Terms.FirstOrDefault(t => t.Active);
        TermLabel.Text = active?.Label ?? snapshot.User.Term;
        var site = snapshot.SiteTerm;
        TermBadge.Text = site?.Key is null ? "" : site.MatchesActive ? "教务当前" : "与教务当前不一致";
        TermBadge.Tone = site?.MatchesActive == true ? Tone.Success : Tone.Danger;
        SiteText.Text = site is null
            ? "教务当前学期将在获取全量课程时读取"
            : site.Key is null
                ? "教务网站当前未开放选课"
                : $"自主选课{(site.ZzxkOpen ? "开放" : "未开放")} · 补退选{(site.TjxkbkkOpen ? "开放" : "未开放")}"
                  + (site.DetectedAt is { } at ? $" · {at}" : "");
        SwitchTermButton.Visibility = Ui.Show(site is { Key: not null, MatchesActive: false });

        var history = snapshot.Terms.Where(t => !t.Active).ToList();
        HistoryButton.Visibility = Ui.Show(history.Count > 0);
        HistoryButton.Content = $"历史学期 {history.Count}";
        HistoryFlyout.Items.Clear();
        foreach (var term in history)
        {
            HistoryFlyout.Items.Add(new MenuFlyoutItem
            {
                Text = term.Label + (term.GroupCount > 0 ? $" · {term.GroupCount} 个方案" : ""),
                IsEnabled = false,
            });
        }
    }

    async void OnSwitchTerm(object sender, RoutedEventArgs e)
    {
        if (store.Snapshot?.SiteTerm?.Key is not { } key) return;
        var parts = key.Split('-');
        if (parts.Length != 2) return;
        if (store.GroupsDirty && !await Ui.Confirm("放弃未保存的方案？", "当前学期的方案还有未保存的修改，切换学期将放弃这些修改。", "切换", destructive: true))
            return;
        await store.SwitchTermAsync(parts[0], parts[1]);
    }

    // ------------------------------------------------------------ 工具栏与目录

    void RenderToolbar()
    {
        rendering = true;
        var categories = new List<string> { CourseFilter.AllCategories };
        categories.AddRange(store.Snapshot?.Categories ?? []);
        if (!(CategoryBox.ItemsSource is List<string> current && current.SequenceEqual(categories)))
            CategoryBox.ItemsSource = categories;
        CategoryBox.SelectedItem = store.CourseFilter.Category;
        SortBox.SelectedIndex = (int)store.CourseFilter.Sort;
        OnlyOpenToggle.IsChecked = store.CourseFilter.OnlyOpen;
        OnlyUnassignedToggle.IsChecked = store.CourseFilter.OnlyUnassigned;
        if (SearchBox.Text != store.CourseFilter.Query) SearchBox.Text = store.CourseFilter.Query;
        SyncCatalogItem.IsEnabled = !store.Running.Contains("bootstrap");
        SyncCatalogItem.Text = store.Running.Contains("bootstrap") ? "正在获取课程…" : "获取全量课程";
        SyncRatingsItem.IsEnabled = !store.Running.Contains("ratings-all");
        DetectTermItem.IsEnabled = !store.Running.Contains("detect-term");
        rendering = false;
    }

    void RenderCourses()
    {
        var rows = store.FilteredCourses;
        var selected = CourseList.SelectedItems.OfType<CourseRow>().Select(c => c.JxbId).ToHashSet();
        rendering = true;
        CourseList.ItemsSource = rows;
        foreach (var row in rows.Where(r => selected.Contains(r.JxbId))) CourseList.SelectedItems.Add(row);
        rendering = false;
        CountText.Text = $"{rows.Count} / {store.Courses.Count}";
        EmptyCourses.Visibility = Ui.Show(rows.Count == 0);
        EmptyCourses.Text = store.Courses.Count == 0 ? "还没有课程目录：点击“同步 → 获取全量课程”" : "没有符合条件的课程";
        UpdateAddButton();
    }

    void OnSearchChanged(AutoSuggestBox sender, AutoSuggestBoxTextChangedEventArgs args)
    {
        if (rendering) return;
        searchDebounce?.Cancel();
        var cts = searchDebounce = new CancellationTokenSource();
        var text = sender.Text;
        _ = Task.Delay(180, cts.Token).ContinueWith(t =>
        {
            if (!t.IsCanceled) DispatcherQueue.TryEnqueue(() => store.CourseFilter = store.CourseFilter with { Query = text });
        }, TaskScheduler.Default);
    }

    void OnFilterChanged(object sender, SelectionChangedEventArgs e)
    {
        if (rendering) return;
        store.CourseFilter = store.CourseFilter with
        {
            Category = CategoryBox.SelectedItem as string ?? CourseFilter.AllCategories,
            Sort = SortBox.SelectedIndex < 0 ? CourseSort.Catalog : (CourseSort)SortBox.SelectedIndex,
        };
    }

    void OnFilterToggled(object sender, RoutedEventArgs e)
    {
        store.CourseFilter = store.CourseFilter with
        {
            OnlyOpen = OnlyOpenToggle.IsChecked == true,
            OnlyUnassigned = OnlyUnassignedToggle.IsChecked == true,
        };
    }

    void OnSyncCatalog(object sender, RoutedEventArgs e) => _ = store.RunAsync("bootstrap");

    void OnSyncRatings(object sender, RoutedEventArgs e) => _ = store.RunAsync("ratings-all");

    void OnDetectTerm(object sender, RoutedEventArgs e) => _ = store.RunAsync("detect-term");

    void OnInspectorToggled(object sender, RoutedEventArgs e)
    {
        var show = InspectorToggle.IsChecked == true;
        Inspector.Visibility = Ui.Show(show);
        InspectorColumn.Width = new GridLength(show ? 320 : 0);
    }

    List<string> SelectedCourseIds() =>
        CourseList.SelectedItems.OfType<CourseRow>().Select(c => c.JxbId).ToList();

    void OnCourseSelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (rendering) return;
        if (e.AddedItems.LastOrDefault() is CourseRow added) inspected = added.JxbId;
        else if (CourseList.SelectedItems.Count > 0 && !SelectedCourseIds().Contains(inspected ?? ""))
            inspected = (CourseList.SelectedItems[^1] as CourseRow)?.JxbId;
        RenderInspector();
        UpdateAddButton();
    }

    void OnCourseDoubleTapped(object sender, DoubleTappedRoutedEventArgs e)
    {
        if ((e.OriginalSource as FrameworkElement)?.DataContext is CourseRow row)
            _ = store.AddCoursesAsync([row.JxbId]);
    }

    void OnCourseMenuOpening(object? sender, object e)
    {
        AddToGroupItem.Text = store.SelectedGroup is { } name ? $"加入“{name}”" : "加入当前方案";
        AddToGroupItem.IsEnabled = store.SelectedGroup is not null && CourseList.SelectedItems.Count > 0;
    }

    void OnAddSelected(object sender, RoutedEventArgs e)
    {
        var ids = SelectedCourseIds();
        if (ids.Count == 0) return;
        _ = AddAndClear(ids);
    }

    async Task AddAndClear(List<string> ids)
    {
        await store.AddCoursesAsync(ids);
        CourseList.SelectedItems.Clear();
    }

    void OnCopyKch(object sender, RoutedEventArgs e) =>
        Ui.CopyText(string.Join("\n", CourseList.SelectedItems.OfType<CourseRow>().Select(c => c.Kch).OfType<string>()));

    void OnCopyJxb(object sender, RoutedEventArgs e) => Ui.CopyText(string.Join("\n", SelectedCourseIds()));

    void UpdateAddButton()
    {
        AddSelectedButton.Content = $"加入所选课程 ({CourseList.SelectedItems.Count})";
        AddSelectedButton.IsEnabled = CourseList.SelectedItems.Count > 0 && store.SelectedGroup is not null;
    }

    // ------------------------------------------------------------ 详情

    void RenderInspector()
    {
        InspectorPanel.Children.Clear();
        if (inspected is null || !store.CoursesById.TryGetValue(inspected, out var course))
        {
            InspectorPanel.Children.Add(new TextBlock
            {
                Text = "选择课程查看详情\n双击课程可加入当前方案",
                Style = (Style)Application.Current.Resources["SecondaryText"],
                TextAlignment = TextAlignment.Center,
                HorizontalAlignment = HorizontalAlignment.Center,
                Margin = new Thickness(0, 40, 0, 0),
                TextWrapping = TextWrapping.Wrap,
            });
            return;
        }

        var header = new StackPanel { Spacing = 2 };
        header.Children.Add(new TextBlock { Text = course.Category, Style = Res("SecondaryText") });
        header.Children.Add(new TextBlock { Text = course.Title, Style = Res("SubtitleTextBlockStyle"), TextWrapping = TextWrapping.Wrap, IsTextSelectionEnabled = true });
        var line = new Grid();
        line.Children.Add(new TextBlock { Text = course.ClassName, Style = Res("SecondaryText") });
        var badge = Ui.Badge(course.Chosen ? "当前已选" : course.AvailabilityText, course.StatusTone);
        badge.HorizontalAlignment = HorizontalAlignment.Right;
        line.Children.Add(badge);
        header.Children.Add(line);
        InspectorPanel.Children.Add(header);

        var rating = new StackPanel { Spacing = 4 };
        rating.Children.Add(new TextBlock { Text = Labels.Of(course.Rating.Status), Style = Res("SecondaryText") });
        var score = new TextBlock { Text = course.Rating.ScoreText, FontSize = 34, FontWeight = Microsoft.UI.Text.FontWeights.SemiBold };
        if (!course.IsRated) score.Foreground = Ui.ToneForeground(Tone.Neutral);
        rating.Children.Add(score);
        rating.Children.Add(new TextBlock
        {
            Text = $"{course.Rating.Count?.ToString() ?? "-"} 条评价 · {course.Rating.Semester ?? "-"} · {course.Rating.Teacher ?? course.Teachers}",
            Style = Res("SecondaryText"),
        });
        if (course.Rating.Message is { } message)
            rating.Children.Add(new TextBlock { Text = message, Style = Res("CaptionTextBlockStyle"), TextWrapping = TextWrapping.Wrap });
        InspectorPanel.Children.Add(Section(rating));

        InspectorPanel.Children.Add(Details("授课信息", ("教师", course.Teachers), ("时间", course.ScheduleText), ("地点", course.LocationText)));
        InspectorPanel.Children.Add(Details("课程标识", ("课程号", course.KchText), ("教学班 ID", course.JxbId), ("所属方案", course.Group ?? "未分配")));
        InspectorPanel.Children.Add(Details("容量", ("已选 / 容量", course.SeatText), ("评价更新", course.Rating.UpdatedAt ?? "-")));
    }

    static Style Res(string key) => (Style)Application.Current.Resources[key];

    static Border Section(UIElement child) => new()
    {
        Background = (Microsoft.UI.Xaml.Media.Brush)Application.Current.Resources["LayerFillColorDefaultBrush"],
        CornerRadius = new CornerRadius(6),
        Padding = new Thickness(12),
        Child = child,
    };

    static UIElement Details(string title, params (string Label, string Value)[] rows)
    {
        var panel = new StackPanel { Spacing = 6 };
        panel.Children.Add(new TextBlock { Text = title, Style = Res("BodyStrongTextBlockStyle") });
        foreach (var (label, value) in rows)
        {
            var grid = new Grid { ColumnSpacing = 12 };
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(78) });
            grid.ColumnDefinitions.Add(new ColumnDefinition());
            grid.Children.Add(new TextBlock { Text = label, Style = Res("SecondaryText") });
            var text = new TextBlock { Text = value, TextWrapping = TextWrapping.Wrap, IsTextSelectionEnabled = true };
            Grid.SetColumn(text, 1);
            grid.Children.Add(text);
            panel.Children.Add(grid);
        }
        return Section(panel);
    }

    // ------------------------------------------------------------ 方案

    void RenderPlan()
    {
        rendering = true;
        var tabs = store.Groups
            .Select(g => new GroupTab(g, $"{store.HeldLabelFor(g)} · {g.Priority.Count} 个", store.ConflictsFor(g).Count))
            .ToList();
        GroupTabs.ItemsSource = tabs;
        GroupTabs.SelectedItem = tabs.FirstOrDefault(t => t.Name == store.SelectedGroup);
        RevertButton.Visibility = Ui.Show(store.GroupsDirty);
        SaveButton.IsEnabled = store.GroupsDirty && !store.Busy;

        var group = store.SelectedGroupData;
        NoGroupText.Visibility = Ui.Show(group is null);
        PlanEditor.Visibility = Ui.Show(group is not null);
        var selected = PriorityList.SelectedItems.OfType<PriorityItem>().Select(i => i.Id).ToHashSet();
        priorityItems.Clear();
        if (group is not null)
        {
            PeCheck.IsChecked = group.IsPe;
            var marks = store.ConflictsFor(group);
            for (var i = 0; i < group.Priority.Count; i++)
            {
                var id = group.Priority[i];
                store.CoursesById.TryGetValue(id, out var course);
                marks.TryGetValue(id, out var mark);
                priorityItems.Add(new PriorityItem
                {
                    Id = id,
                    Index = (i + 1).ToString(),
                    Title = course is null ? Labels.ShortId(id) : $"{course.Title} · {course.ClassName}",
                    Summary = course?.Summary ?? id,
                    Note = mark?.Note ?? "",
                    BadgeText = course?.Chosen == true ? "当前持有" : mark?.Badge ?? course?.AvailabilityText ?? "",
                    BadgeTone = course?.Chosen == true ? Tone.Accent : mark is not null ? Tone.Danger : course?.StatusTone ?? Tone.Neutral,
                });
            }
            foreach (var item in priorityItems.Where(i => selected.Contains(i.Id))) PriorityList.SelectedItems.Add(item);
            EmptyPlan.Visibility = Ui.Show(group.Priority.Count == 0);
        }
        rendering = false;
        UpdateMemberButtons();
        UpdateAddButton();
    }

    void OnGroupTabChanged(object sender, SelectionChangedEventArgs e)
    {
        if (rendering || GroupTabs.SelectedItem is not GroupTab tab) return;
        PriorityList.SelectedItems.Clear();
        store.SelectedGroup = tab.Name;
    }

    void OnNewGroupKeyDown(object sender, KeyRoutedEventArgs e)
    {
        if (e.Key == VirtualKey.Enter) OnCreateGroup(sender, e);
    }

    void OnCreateGroup(object sender, RoutedEventArgs e)
    {
        if (!store.CreateGroup(NewGroupName.Text)) return;
        NewGroupName.Text = "";
        NewGroupFlyout.Hide();
    }

    void OnRevert(object sender, RoutedEventArgs e) => store.RevertGroups();

    void OnSave(object sender, RoutedEventArgs e) => _ = store.SaveGroupsAsync();

    void OnPeToggled(object sender, RoutedEventArgs e) => store.SetPe(PeCheck.IsChecked == true);

    List<string> SelectedMembers() => PriorityList.SelectedItems.OfType<PriorityItem>().Select(i => i.Id).ToList();

    void OnMemberSelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (!rendering) UpdateMemberButtons();
    }

    void UpdateMemberButtons()
    {
        var count = PriorityList.SelectedItems.Count;
        MoveUpButton.IsEnabled = count == 1;
        MoveDownButton.IsEnabled = count == 1;
        HeldButton.IsEnabled = count == 1;
        RemoveButton.IsEnabled = count > 0;
    }

    /// 拖拽排序完成后,以列表当前顺序为准写回方案。
    void OnPriorityReordered(ListViewBase sender, DragItemsCompletedEventArgs args) =>
        store.SetPriority(priorityItems.Select(i => i.Id));

    void OnMoveUp(object sender, RoutedEventArgs e) => MoveSelected(-1);

    void OnMoveDown(object sender, RoutedEventArgs e) => MoveSelected(1);

    void MoveSelected(int delta)
    {
        if (SelectedMembers() is not [var id]) return;
        store.MoveMember(id, delta);
        if (priorityItems.FirstOrDefault(i => i.Id == id) is { } item) PriorityList.SelectedItem = item;
    }

    void OnSetHeld(object sender, RoutedEventArgs e)
    {
        if (SelectedMembers() is [var id]) store.SetAsHeld(id);
    }

    void OnRemoveMembers(object sender, RoutedEventArgs e) => store.RemoveMembers(SelectedMembers());

    void OnPriorityKeyDown(object sender, KeyRoutedEventArgs e)
    {
        if (e.Key == VirtualKey.Delete)
        {
            store.RemoveMembers(SelectedMembers());
            e.Handled = true;
        }
    }

    async void OnDeleteGroup(object sender, RoutedEventArgs e)
    {
        if (store.SelectedGroup is not { } name) return;
        if (await Ui.Confirm($"删除方案“{name}”？", "保存后该方案及其优先级配置将被移除。", "删除", destructive: true))
            store.DeleteSelectedGroup();
    }
}
