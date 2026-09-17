[CmdletBinding()]
param(
  [ValidateSet("x64", "arm64")]
  [string]$Architecture = "x64",

  # PyInstaller 冻结的后端目录(含 sjtu-backend.exe)
  [string]$BackendDir = "src-tauri/resources/sjtu-backend",

  [string]$OutputRoot = "build/windows"
)

# 发布 交我选 Windows 客户端(WinUI 3,非打包、自包含 .NET 与 Windows App SDK),
# 并把冻结后端放到 <输出>\sjtu-backend\,BackendLocator 会从这里找到它。
# 输出:build/windows/<arch>/app —— 安装程序与 MSIX 都从这个目录打包。
$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$project = Join-Path $projectRoot "ng/windows/JiaoWoXuan/JiaoWoXuan.csproj"
$backend = Join-Path $projectRoot $BackendDir
$appDir = Join-Path $projectRoot "$OutputRoot/$Architecture/app"
$platform = if ($Architecture -eq "arm64") { "ARM64" } else { "x64" }

if (-not (Test-Path -LiteralPath (Join-Path $backend "sjtu-backend.exe"))) {
  throw "未找到冻结后端：$backend\sjtu-backend.exe。请先运行 PyInstaller sjtu-backend.spec。"
}

if (Test-Path -LiteralPath $appDir) { Remove-Item -LiteralPath $appDir -Recurse -Force }

dotnet publish $project -c Release -r "win-$Architecture" -p:Platform=$platform `
  -p:SelfContained=true -p:WindowsAppSDKSelfContained=true -p:DebugType=None -p:DebugSymbols=false `
  -o $appDir
if ($LASTEXITCODE -ne 0) { throw "dotnet publish 失败，退出码：$LASTEXITCODE" }

Copy-Item -LiteralPath $backend -Destination (Join-Path $appDir "sjtu-backend") -Recurse

# 不得把运行期数据打进发行包
$forbidden = @('.env', 'secrets.local.json', 'session.json', 'state.json', 'swap_state.json', 'user_settings.json',
  'catalog.json', 'zzxk_capacity.json', 'seat_details.json', 'ratings.json', 'changes.log')
$found = Get-ChildItem -LiteralPath $appDir -Recurse -File | Where-Object { $_.Name -in $forbidden }
if ($found) { throw "发行包里混入了运行期数据：$($found.FullName -join ', ')" }

if (-not (Test-Path -LiteralPath (Join-Path $appDir "JiaoWoXuan.exe"))) { throw "发布目录缺少 JiaoWoXuan.exe" }
# 缺少应用自身的 PRI/XBF 时窗口创建即 XamlParseException
if (-not (Test-Path -LiteralPath (Join-Path $appDir "JiaoWoXuan.pri"))) { throw "发布目录缺少 JiaoWoXuan.pri" }
foreach ($xbf in 'App.xbf', 'MainWindow.xbf', 'Pages\OverviewPage.xbf') {
  if (-not (Test-Path -LiteralPath (Join-Path $appDir $xbf))) { throw "发布目录缺少 $xbf" }
}
Write-Host "已发布：$appDir"
