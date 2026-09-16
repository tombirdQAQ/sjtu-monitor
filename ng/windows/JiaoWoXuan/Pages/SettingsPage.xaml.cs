using System.ComponentModel;
using JiaoWoXuan.Core;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace JiaoWoXuan.Pages;

public sealed partial class SettingsPage : Microsoft.UI.Xaml.Controls.Page
{
    static readonly string[] Themes = ["system", "light", "dark"];
    readonly AppStore store = App.Store;
    bool rendering;

    public SettingsPage()
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
        if (e.PropertyName is nameof(AppStore.Settings)) Render();
        if (e.PropertyName is nameof(AppStore.SettingsDirty) or nameof(AppStore.Busy)) RenderFooter();
    }

    static string Prompt(bool? saved, string unsaved = "未保存") => saved == true ? "已安全保存，留空不修改" : unsaved;

    void Render()
    {
        rendering = true;
        var s = store.Settings;
        ThemeBox.SelectedIndex = Math.Max(0, Array.IndexOf(Themes, UiSettings.Theme));
        if (JaccountUser.Text != s.JaccountUser) JaccountUser.Text = s.JaccountUser;
        if (JaccountPass.Password != s.JaccountPass) JaccountPass.Password = s.JaccountPass;
        JaccountPass.PlaceholderText = Prompt(s.HasJaccountPass);
        if (CoursePlusPass.Password != s.CoursePlusPassword) CoursePlusPass.Password = s.CoursePlusPassword;
        CoursePlusPass.PlaceholderText = Prompt(s.HasCoursePlusPassword);
        SecretHint.Text = $"密码不回显，保存在系统安全存储（{s.SecretBackend ?? "未知"}）。";
        PollMin.Value = s.PollMin;
        PollMax.Value = s.PollMax;
        EmailEnabled.IsOn = s.EmailEnabled;
        if (SmtpHost.Text != s.SmtpHost) SmtpHost.Text = s.SmtpHost;
        SmtpPort.Value = s.SmtpPort;
        if (SmtpUser.Text != s.SmtpUser) SmtpUser.Text = s.SmtpUser;
        if (SmtpPass.Password != s.SmtpPass) SmtpPass.Password = s.SmtpPass;
        SmtpPass.PlaceholderText = s.HasSmtpPass != true ? "未保存"
            : s.SmtpPassFallback == true ? "默认复用 JAccount 密码，可单独设置" : "已安全保存，留空不修改";
        if (MailFrom.Text != s.MailFrom) MailFrom.Text = s.MailFrom;
        if (MailTo.Text != s.MailTo) MailTo.Text = s.MailTo;
        DevSection.Visibility = Ui.Show(!store.ReleaseMode);
        DebugToggle.IsOn = store.Debug;
        DataDirText.Text = store.Hello is { } hello ? $"数据目录：{hello.DataDir}" : "";
        rendering = false;
        RenderFooter();
    }

    void RenderFooter()
    {
        DirtyText.Visibility = Ui.Show(store.SettingsDirty);
        SaveButton.IsEnabled = store.SettingsDirty && !store.Busy && store.IsReady;
        TestMailButton.IsEnabled = !store.Busy && store.IsReady;
    }

    /// 把表单写回 store.Settings(record,整体替换以触发脏标记)。
    void Collect()
    {
        if (rendering) return;
        store.Settings = store.Settings with
        {
            JaccountUser = JaccountUser.Text.Trim(),
            JaccountPass = JaccountPass.Password,
            CoursePlusPassword = CoursePlusPass.Password,
            PollMin = double.IsNaN(PollMin.Value) ? store.Settings.PollMin : (int)PollMin.Value,
            PollMax = double.IsNaN(PollMax.Value) ? store.Settings.PollMax : (int)PollMax.Value,
            EmailEnabled = EmailEnabled.IsOn,
            SmtpHost = SmtpHost.Text.Trim(),
            SmtpPort = double.IsNaN(SmtpPort.Value) ? store.Settings.SmtpPort : (int)SmtpPort.Value,
            SmtpUser = SmtpUser.Text.Trim(),
            SmtpPass = SmtpPass.Password,
            MailFrom = MailFrom.Text.Trim(),
            MailTo = MailTo.Text.Trim(),
        };
    }

    void OnEdited(object sender, RoutedEventArgs e) => Collect();

    void OnNumberEdited(NumberBox sender, NumberBoxValueChangedEventArgs args) => Collect();

    void OnThemeChanged(object sender, SelectionChangedEventArgs e)
    {
        if (rendering || ThemeBox.SelectedIndex < 0) return;
        UiSettings.Theme = Themes[ThemeBox.SelectedIndex];
        if (App.MainWindow?.Content is FrameworkElement root) UiSettings.ApplyTheme(root);
    }

    void OnDebugToggled(object sender, RoutedEventArgs e)
    {
        if (!rendering) store.Debug = DebugToggle.IsOn;
    }

    void OnSave(object sender, RoutedEventArgs e)
    {
        if (store.Settings.PollMax < store.Settings.PollMin)
        {
            App.MainWindow?.DispatcherQueue.TryEnqueue(async () =>
                await Ui.Confirm("轮询间隔无效", "最大间隔不能小于最小间隔。", "好"));
            return;
        }
        _ = store.SaveSettingsAsync();
    }

    void OnTestMail(object sender, RoutedEventArgs e) => _ = store.SendTestEmailAsync();
}
