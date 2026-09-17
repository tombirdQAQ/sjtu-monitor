# Microsoft Store 发布说明

本项目通过 MSIX bundle（x64 + ARM64，WinUI 3 原生客户端）提交 Microsoft Store；GitHub Release 另提供 Inno Setup 独立安装程序供直装。

## Store 身份（不可修改）

| 字段 | 值 |
| --- | --- |
| Identity Name | `SJTU.5685085ABA108` |
| Publisher | `CN=3D526C73-BBEC-4792-8363-1034EBA5483A` |
| Publisher display name | `SJTU` |
| Store ID | `9PPT8WJ06C0G` |

`Package Family Name` 和 `Package SID` 是安装后的运行时标识，不写入 manifest。

## 首次发布前

1. 将 Partner Center 的隐私政策 URL 设置为 `https://github.com/tangmubai/sjtu-monitor/blob/develop/docs/privacy-policy.md`。
2. 创建一个可导出的 PFX，并在 GitHub Actions Secrets 创建 `MSIX_CERTIFICATE_BASE64` 与 `MSIX_CERTIFICATE_PASSWORD`。PFX 的 Subject 必须与 manifest 中的 Publisher 完全一致。可在 PowerShell 中执行：

   ```powershell
   $password = Read-Host -AsSecureString 'PFX password'
   $cert = New-SelfSignedCertificate -Type Custom -Subject 'CN=3D526C73-BBEC-4792-8363-1034EBA5483A' -KeyUsage DigitalSignature -KeyExportPolicy Exportable -CertStoreLocation Cert:\CurrentUser\My -HashAlgorithm SHA256
   Export-PfxCertificate -Cert $cert -FilePath .\sjtu-monitor-store-signing.pfx -Password $password
   [Convert]::ToBase64String([System.IO.File]::ReadAllBytes('.\sjtu-monitor-store-signing.pfx'))
   ```

   将最后一行输出完整复制到 `MSIX_CERTIFICATE_BASE64`；将创建时输入的密码放入 `MSIX_CERTIFICATE_PASSWORD`。不要提交 PFX 文件。
3. 在 Windows SDK 安装 `MakeAppx.exe`、`SignTool.exe` 与 Windows App Certification Kit。Windows ARM64 可运行前两个工具，但 WACK 目前没有可安装的 ARM64 主组件；请在 x64 Windows 机器或 x64 Windows VM 上完成下一步。
4. 在 x64 Windows 上使用 Release MSIX 安装后，运行 `appcert.exe reset`，再执行 `appcert.exe test -appxpackagepath <MSIX路径> -reportoutputpath <XML报告路径>`。
5. 准备商店说明、支持链接、隐私政策、中文截图和审核说明。审核说明应指出：JAccount 由用户主动填写；网络同步必须由用户点击发起；应用并非上海交通大学官方产品。

## 应对“无法测试 / 需要测试账号”退回

Microsoft 认证要求审核人员能在无校园网、无 JAccount 的情况下体验主要功能。为此应用内置**演示模式**：首屏“连接 JAccount”步骤左下角有“以演示模式预览”按钮，点击后无需登录即进入完整工作台，加载示例课程/方案/评分/换课记录，所有联网与写入操作均被禁用（顶部显示“演示模式”横幅，可随时“退出演示”）。演示数据全部离线打包，不依赖 i.sjtu.edu.cn 或校园网。

### Notes for Certification（提交时填入 Submission Options → Notes for Certification）

```
This app is a course-availability monitor for enrolled students of Shanghai
Jiao Tong University (SJTU). Primary functionality normally requires a personal
JAccount issued by the university and access to the campus network, so we cannot
provide a shared test account.

To evaluate the app WITHOUT an account or campus network, on the first screen
("连接 JAccount" / Connect JAccount) click the secondary button
"以演示模式预览" (Preview in demo mode). This skips login and loads the full
workbench with bundled sample data; all network and write actions are disabled.
A "演示模式 / Demo mode" banner is shown and can be exited at any time.

How users obtain an account: a JAccount is issued by SJTU to enrolled students
and staff (https://jaccount.sjtu.edu.cn). Non-SJTU users cannot obtain one and
should use the built-in demo mode. This app is not an official SJTU product.
```

### Store 描述需包含的账号获取说明（解决“无 in-app/metadata 指引”退回）

在商店描述中加入类似段落，明确目标用户与账号来源：

```
本应用面向上海交通大学（SJTU）在校师生，用于监控 i.sjtu.edu.cn 的选课余量。
登录需使用学校统一分配的 JAccount（申领与说明见 https://jaccount.sjtu.edu.cn），
非交大用户无法获取账号。首次启动可点击“以演示模式预览”，无需账号即可离线体验
全部界面与示例数据。本应用非上海交通大学官方产品。

This app monitors SJTU course seat availability. Sign-in requires a JAccount
issued by Shanghai Jiao Tong University to its students/staff
(https://jaccount.sjtu.edu.cn); non-SJTU users cannot obtain one. On first launch
you can choose "Preview in demo mode" to explore the full UI offline with sample
data, no account needed. Not an official SJTU product.
```

## 本地打包

先冻结后端并发布两个架构的应用，再打包 msixbundle：

```powershell
node scripts/check-release-version.mjs
python -m PyInstaller sjtu-backend.spec --distpath src-tauri/resources --noconfirm
pwsh -File packaging/windows/publish.ps1 -Architecture x64
pwsh -File packaging/windows/publish.ps1 -Architecture arm64
pwsh -File packaging/build-msix.ps1 -Version 1.0.0.0 -CertificatePath .\store-signing.pfx -CertificatePassword '<password>'
```

提交 Partner Center 时上传 GitHub 草稿 Release 中的 `JiaoWoXuan-<版本>-store.msixbundle`。
