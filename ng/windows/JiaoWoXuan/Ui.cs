using System.Text.Json;
using JiaoWoXuan.Core;
using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Windows.UI;

namespace JiaoWoXuan;

/// 界面偏好(主题、托盘提示),存在 %LOCALAPPDATA%\sjtu-monitor-ng\ui.json。
/// 非打包应用没有 ApplicationData.LocalSettings,所以自己存。
public static class UiSettings
{
    sealed class Data
    {
        public string Theme { get; set; } = "system";
        public bool TrayHintShown { get; set; }
    }

    static readonly string FilePath = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "sjtu-monitor-ng", "ui.json");

    static readonly Data data = Load();

    static Data Load()
    {
        try
        {
            return JsonSerializer.Deserialize<Data>(File.ReadAllText(FilePath)) ?? new Data();
        }
        catch (Exception)
        {
            return new Data();
        }
    }

    static void Save()
    {
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(FilePath)!);
            File.WriteAllText(FilePath, JsonSerializer.Serialize(data));
        }
        catch (Exception)
        {
        }
    }

    /// "system" | "light" | "dark"
    public static string Theme
    {
        get => data.Theme;
        set
        {
            data.Theme = value;
            Save();
        }
    }

    public static bool TrayHintShown
    {
        get => data.TrayHintShown;
        set
        {
            data.TrayHintShown = value;
            Save();
        }
    }

    public static void ApplyTheme(FrameworkElement root)
    {
        root.RequestedTheme = Theme switch
        {
            "light" => ElementTheme.Light,
            "dark" => ElementTheme.Dark,
            _ => ElementTheme.Default,
        };
    }
}

public static class Ui
{
    public static AppStore Store => App.Store;

    public static Brush ToneForeground(Tone tone) => tone switch
    {
        Tone.Accent => Resource("AccentTextFillColorPrimaryBrush"),
        Tone.Success => Resource("SystemFillColorSuccessBrush"),
        Tone.Danger => Resource("SystemFillColorCriticalBrush"),
        Tone.Warning => Resource("SystemFillColorCautionBrush"),
        _ => Resource("TextFillColorSecondaryBrush"),
    };

    public static Brush ToneBackground(Tone tone) => tone switch
    {
        Tone.Accent => Resource("AccentFillColorSelectedTextBackgroundBrush", 0.18),
        Tone.Success => Resource("SystemFillColorSuccessBackgroundBrush"),
        Tone.Danger => Resource("SystemFillColorCriticalBackgroundBrush"),
        Tone.Warning => Resource("SystemFillColorCautionBackgroundBrush"),
        _ => Resource("ControlFillColorSecondaryBrush"),
    };

    static Brush Resource(string key, double? opacity = null)
    {
        if (Application.Current.Resources.TryGetValue(key, out var value) && value is SolidColorBrush brush)
        {
            return opacity is { } o ? new SolidColorBrush(brush.Color) { Opacity = o } : brush;
        }
        return new SolidColorBrush(Colors.Gray);
    }

    public static Visibility Show(bool value) => value ? Visibility.Visible : Visibility.Collapsed;

    public static Visibility ShowText(string? value) => string.IsNullOrEmpty(value) ? Visibility.Collapsed : Visibility.Visible;

    public static Border Badge(string text, Tone tone) => new()
    {
        Background = ToneBackground(tone),
        CornerRadius = new CornerRadius(8),
        Padding = new Thickness(7, 1, 7, 2),
        VerticalAlignment = VerticalAlignment.Center,
        HorizontalAlignment = HorizontalAlignment.Left,
        Child = new TextBlock
        {
            Text = text,
            FontSize = 12,
            Foreground = ToneForeground(tone),
            TextTrimming = TextTrimming.CharacterEllipsis,
        },
    };

    public static Task<bool> Confirm(string title, string message, string primary, bool destructive = false) =>
        App.MainWindow!.ConfirmAsync(title, message, primary, destructive);

    public static void CopyText(string text)
    {
        var package = new Windows.ApplicationModel.DataTransfer.DataPackage();
        package.SetText(text);
        Windows.ApplicationModel.DataTransfer.Clipboard.SetContent(package);
    }
}

/// 状态标签(小胶囊),对应 macOS 版 StatusBadge。
public sealed partial class StatusBadge : ContentControl
{
    public static readonly DependencyProperty TextProperty = DependencyProperty.Register(
        nameof(Text), typeof(string), typeof(StatusBadge), new PropertyMetadata("", (d, _) => ((StatusBadge)d).Update()));

    public static readonly DependencyProperty ToneProperty = DependencyProperty.Register(
        nameof(Tone), typeof(Tone), typeof(StatusBadge), new PropertyMetadata(Tone.Neutral, (d, _) => ((StatusBadge)d).Update()));

    public string Text
    {
        get => (string)GetValue(TextProperty);
        set => SetValue(TextProperty, value);
    }

    public Tone Tone
    {
        get => (Tone)GetValue(ToneProperty);
        set => SetValue(ToneProperty, value);
    }

    public StatusBadge()
    {
        VerticalAlignment = VerticalAlignment.Center;
        HorizontalAlignment = HorizontalAlignment.Left;
        IsTabStop = false;
        Update();
    }

    void Update()
    {
        Visibility = string.IsNullOrEmpty(Text) ? Visibility.Collapsed : Visibility.Visible;
        Content = Ui.Badge(Text ?? "", Tone);
    }
}

/// 托盘右键菜单是 Win32 弹出菜单,不跟随 WinUI 主题;通过 uxtheme 的 SetPreferredAppMode 让它支持深色。
/// (资源管理器、记事本等系统应用同样使用这组接口。)
public static partial class NativeTheme
{
    [System.Runtime.InteropServices.DllImport("uxtheme.dll", EntryPoint = "#135")]
    static extern int SetPreferredAppMode(int mode);

    [System.Runtime.InteropServices.DllImport("uxtheme.dll", EntryPoint = "#136")]
    static extern void FlushMenuThemes();

    /// theme: "system" | "light" | "dark"
    public static void ApplyMenuTheme(string theme)
    {
        try
        {
            // 1 = AllowDark(跟随系统) 2 = ForceDark 3 = ForceLight
            SetPreferredAppMode(theme switch { "dark" => 2, "light" => 3, _ => 1 });
            FlushMenuThemes();
        }
        catch (Exception)
        {
            // 旧系统没有这组导出,保持默认浅色菜单即可。
        }
    }
}
