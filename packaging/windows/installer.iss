; 交我选 Windows 独立安装程序(Inno Setup 6)。
;
;   ISCC /DAppVersion=1.0.0 /DArch=x64 packaging\windows\installer.iss
;
; 输入:build\windows\<Arch>\app(packaging\windows\publish.ps1 的输出)
; 输出:build\windows\JiaoWoXuan-<版本>-windows-<Arch>-setup.exe
;
; 默认按当前用户安装(无需管理员),安装时也可选择为所有用户安装。

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef Arch
  #define Arch "x64"
#endif

#define AppName "交我选"
#define AppExe "JiaoWoXuan.exe"
#define SourceDir "..\..\build\windows\" + Arch + "\app"

[Setup]
AppId={{6E4B9E0C-3A5F-4B8E-9A1D-7C2F5E8B4D31}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=SJTU
AppPublisherURL=https://github.com/tombirdQAQ/sjtu-monitor
AppSupportURL=https://github.com/tombirdQAQ/sjtu-monitor/issues
DefaultDirName={autopf}\JiaoWoXuan
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\..\build\windows
OutputBaseFilename=JiaoWoXuan-{#AppVersion}-windows-{#Arch}-setup
SetupIconFile=..\..\ng\windows\JiaoWoXuan\Assets\AppIcon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
MinVersion=10.0.19041
CloseApplications=yes
RestartApplications=no
#if Arch == "arm64"
ArchitecturesAllowed=arm64
ArchitecturesInstallIn64BitMode=arm64
#else
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
#endif

[Languages]
#ifexist "compiler:Languages\ChineseSimplified.isl"
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
#endif
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; 卸载前结束仍在后台(托盘)运行的程序及其后端进程;用户数据(%APPDATA%\com.sj-tu.sjtu-monitor)保留。
Filename: "{sys}\taskkill.exe"; Parameters: "/f /t /im {#AppExe}"; Flags: runhidden; RunOnceId: "KillApp"
