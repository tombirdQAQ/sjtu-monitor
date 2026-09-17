## 交我选 1.0.0

全新的原生客户端：macOS 使用 SwiftUI（macOS 26 上启用 Liquid Glass），Windows 使用 WinUI 3（Mica、跟随系统深浅色）。取代此前基于 Tauri 的界面，监控、换课、评分等后端逻辑不变，原有数据自动沿用。

### 下载

| 平台 | 文件 |
| --- | --- |
| Windows x64 | `JiaoWoXuan-<版本>-windows-x64-setup.exe` |
| Windows ARM64 | `JiaoWoXuan-<版本>-windows-arm64-setup.exe` |
| macOS（Apple Silicon，macOS 14+） | `JiaoWoXuan-<版本>-macos-arm64.dmg` |

`*-store.msixbundle` 仅用于提交 Microsoft Store，请勿直接安装。

### 新功能与改进

- 原生界面：侧栏导航、可点击列头排序的课程目录、课程详情面板、拖拽调整方案优先级、菜单栏/托盘常驻（关闭窗口后监控继续运行）、系统通知。
- 自动换课档位改为「关闭 / 通知 / 启用」；通知模式只提醒可换入的课程，不再误报“抢课成功”。
- 日志页重做：按级别统计与筛选，已选课程抓取失败/恢复等事件以可读文字显示。
- 演示模式：无需 JAccount 与校园网即可用示例数据体验全部界面。

### 注意

- macOS 版未做 Developer ID 签名与公证，首次打开请右键「打开」，或执行 `xattr -dr com.apple.quarantine /Applications/交我选.app`。
- 本应用面向上海交通大学在校师生，需使用学校分配的 JAccount；非上海交通大学官方产品。
