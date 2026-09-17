using System.ComponentModel;
using JiaoWoXuan.Core;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Navigation;
using Windows.System;

namespace JiaoWoXuan.Pages;

public sealed partial class OnboardingPage : Microsoft.UI.Xaml.Controls.Page
{
    static readonly string[] StepNames = ["保存账号", "同步课程", "配置方案"];
    readonly AppStore store = App.Store;

    public OnboardingPage()
    {
        InitializeComponent();
        Console.ItemsSource = store.BootstrapLines;
    }

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        store.PropertyChanged += OnStoreChanged;
        store.BootstrapLines.CollectionChanged += OnLinesChanged;
        Account.Text = store.Settings.JaccountUser;
        Render();
    }

    protected override void OnNavigatedFrom(NavigationEventArgs e)
    {
        store.PropertyChanged -= OnStoreChanged;
        store.BootstrapLines.CollectionChanged -= OnLinesChanged;
    }

    void OnStoreChanged(object? sender, PropertyChangedEventArgs e) => Render();

    void OnLinesChanged(object? sender, System.Collections.Specialized.NotifyCollectionChangedEventArgs e) =>
        ConsoleBorder.Visibility = Ui.Show(store.BootstrapLines.Count > 0);

    void Render()
    {
        var step = store.OnboardingStep;
        Steps.Children.Clear();
        for (var i = 0; i < StepNames.Length; i++)
        {
            var reached = step >= i + 1;
            Steps.Children.Add(Ui.Badge($"{i + 1}  {StepNames[i]}", reached ? Tone.Accent : Tone.Neutral));
        }
        AccountStep.Visibility = Ui.Show(step == 1);
        SyncStep.Visibility = Ui.Show(step == 2);
        FinishStep.Visibility = Ui.Show(step >= 3);

        AccountHint.Text = $"凭据保存在系统安全存储（{store.Settings.SecretBackend ?? "未知"}）中。本步骤不会发起网络请求。";
        Password.PlaceholderText = store.Settings.HasJaccountPass == true ? "已安全保存，留空不修改" : "请输入密码";
        var syncing = store.Running.Contains("bootstrap");
        SyncButton.Content = syncing ? "同步中…" : "开始同步课程";
        SyncButton.IsEnabled = !syncing;
        BackButton.IsEnabled = !syncing;
        SyncRing.IsActive = syncing;
        ConsoleBorder.Visibility = Ui.Show(store.BootstrapLines.Count > 0);
        SaveAccountButton.IsEnabled = !store.Busy;
        FinishButton.IsEnabled = !store.Busy;
        StatusText.Text = store.Status;
    }

    void OnSaveAccount(object sender, RoutedEventArgs e)
    {
        store.Settings = store.Settings with { JaccountUser = Account.Text.Trim(), JaccountPass = Password.Password };
        _ = store.SaveOnboardingAccountAsync();
    }

    void OnPasswordKeyDown(object sender, KeyRoutedEventArgs e)
    {
        if (e.Key == VirtualKey.Enter) OnSaveAccount(sender, e);
    }

    void OnBack(object sender, RoutedEventArgs e) => store.OnboardingStep = 1;

    void OnDemo(object sender, RoutedEventArgs e) => _ = store.EnterDemoAsync();

    void OnSync(object sender, RoutedEventArgs e) => _ = store.RunAsync("bootstrap", adoptSiteTerm: true);

    void OnFinish(object sender, RoutedEventArgs e) => _ = store.FinishOnboardingAsync();
}
