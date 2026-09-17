[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$Version,

  # 要放进 msixbundle 的架构;每个架构需先用 packaging/windows/publish.ps1 发布
  [string[]]$Architectures = @("x64", "arm64"),

  [string]$OutputRoot = "build/windows",

  [string]$OutputPath = "build/windows/JiaoWoXuan.msixbundle",

  [string]$CertificatePath,

  [string]$CertificatePassword,

  [switch]$SkipSign
)

# 生成 Microsoft Store 提交用的 MSIX bundle(x64 + ARM64)。
# 每个架构的包内容 = publish.ps1 的输出目录(WinUI 自包含 + sjtu-backend),以完全信任桌面应用运行。
$ErrorActionPreference = "Stop"

function Find-WindowsSdkTool([string]$ToolName) {
  $command = Get-Command $ToolName -ErrorAction SilentlyContinue
  if ($command) { return $command.Source }

  $hostArch = if ([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture -eq "Arm64") { "arm64" } else { "x64" }
  $roots = @(
    (Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"),
    (Join-Path ${env:ProgramFiles} "Windows Kits\10\bin")
  ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
  foreach ($root in $roots) {
    $match = Get-ChildItem -LiteralPath $root -Recurse -Filter $ToolName -File -ErrorAction SilentlyContinue |
      Where-Object { $_.FullName -match "\\($hostArch|x64|x86)\\" } |
      Sort-Object FullName -Descending |
      Select-Object -First 1
    if ($match) { return $match.FullName }
  }
  throw "未找到 $ToolName。请安装 Windows 10/11 SDK，并确保其 bin 目录可访问。"
}

if ($Version -notmatch '^\d+\.\d+\.\d+\.\d+$') {
  throw "MSIX 版本必须是四段数字，例如 1.0.0.0；收到：$Version"
}

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$template = Join-Path $PSScriptRoot "Package.appxmanifest.template"
$output = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $OutputPath))
$work = Join-Path $projectRoot "$OutputRoot/msix"
$packagesDir = Join-Path $work "packages"

$makeAppx = Find-WindowsSdkTool "MakeAppx.exe"
$signTool = if ($SkipSign) { $null } else { Find-WindowsSdkTool "SignTool.exe" }

if (Test-Path -LiteralPath $work) { Remove-Item -LiteralPath $work -Recurse -Force }
New-Item -ItemType Directory -Force -Path $packagesDir | Out-Null

foreach ($arch in $Architectures) {
  $appDir = Join-Path $projectRoot "$OutputRoot/$arch/app"
  if (-not (Test-Path -LiteralPath (Join-Path $appDir "JiaoWoXuan.exe"))) {
    throw "未找到 $arch 发布目录：$appDir。请先运行 packaging/windows/publish.ps1 -Architecture $arch"
  }
  $stage = Join-Path $work "stage-$arch"
  Copy-Item -LiteralPath $appDir -Destination $stage -Recurse

  $assets = Join-Path $stage "Assets"
  New-Item -ItemType Directory -Force -Path $assets | Out-Null
  $iconRoot = Join-Path $projectRoot "src-tauri/icons"
  foreach ($icon in @("StoreLogo.png", "Square44x44Logo.png", "Square150x150Logo.png", "Square310x310Logo.png")) {
    Copy-Item -LiteralPath (Join-Path $iconRoot $icon) -Destination $assets -Force
  }
  Add-Type -AssemblyName System.Drawing
  $squareLogo = [System.Drawing.Image]::FromFile((Join-Path $assets "Square310x310Logo.png"))
  $wideLogo = [System.Drawing.Bitmap]::new(310, 150)
  $graphics = [System.Drawing.Graphics]::FromImage($wideLogo)
  try {
    $graphics.Clear([System.Drawing.Color]::FromArgb(7, 89, 133))
    $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $graphics.DrawImage($squareLogo, [System.Drawing.Rectangle]::new(80, 0, 150, 150))
    $wideLogo.Save((Join-Path $assets "Wide310x150Logo.png"), [System.Drawing.Imaging.ImageFormat]::Png)
  } finally {
    $graphics.Dispose()
    $wideLogo.Dispose()
    $squareLogo.Dispose()
  }

  $manifest = (Get-Content -LiteralPath $template -Raw).
    Replace("__MSIX_VERSION__", $Version).
    Replace("__ARCHITECTURE__", $arch)
  [System.IO.File]::WriteAllText((Join-Path $stage "AppxManifest.xml"), $manifest, [System.Text.UTF8Encoding]::new($false))

  $package = Join-Path $packagesDir "JiaoWoXuan_$($Version)_$arch.msix"
  & $makeAppx pack /d $stage /p $package /o | Write-Host
  if ($LASTEXITCODE -ne 0) { throw "MakeAppx 打包 $arch 失败，退出码：$LASTEXITCODE" }
  Remove-Item -LiteralPath $stage -Recurse -Force
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $output) | Out-Null
if (Test-Path -LiteralPath $output) { Remove-Item -LiteralPath $output -Force }
& $makeAppx bundle /d $packagesDir /p $output /bv $Version /o | Write-Host
if ($LASTEXITCODE -ne 0) { throw "MakeAppx bundle 失败，退出码：$LASTEXITCODE" }

if (-not $SkipSign) {
  if (-not $CertificatePath -or -not $CertificatePassword) {
    throw "Store 产物必须签名。请提供 -CertificatePath 与 -CertificatePassword，或仅用于结构检查时传入 -SkipSign。"
  }
  & $signTool sign /fd SHA256 /f $CertificatePath /p $CertificatePassword $output | Write-Host
  if ($LASTEXITCODE -ne 0) { throw "SignTool 签名失败，退出码：$LASTEXITCODE" }
}

Remove-Item -LiteralPath $work -Recurse -Force
Write-Host "MSIX bundle 已生成：$output"
