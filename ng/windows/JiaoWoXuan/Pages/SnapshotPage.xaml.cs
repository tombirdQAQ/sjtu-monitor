using System.ComponentModel;
using JiaoWoXuan.Core;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace JiaoWoXuan.Pages;

public sealed partial class SnapshotPage : Microsoft.UI.Xaml.Controls.Page
{
    readonly AppStore store = App.Store;
    bool rendering;

    public SnapshotPage()
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
        if (e.PropertyName is nameof(AppStore.StateRows) or nameof(AppStore.Snapshot)) Render();
    }

    void Render()
    {
        rendering = true;
        FilterBar.SelectedItem = FilterBar.Items[(int)store.StateFilter];
        rendering = false;
        var rows = store.StateRows;
        Rows.ItemsSource = rows;
        Empty.Visibility = Ui.Show(rows.Count == 0);
    }

    void OnFilterChanged(SelectorBar sender, SelectorBarSelectionChangedEventArgs args)
    {
        if (rendering || sender.SelectedItem?.Tag is not string tag) return;
        store.StateFilter = Enum.Parse<StateFilter>(tag);
    }
}
