# 交我选 ng（原生客户端 beta）设计

## 目标
- macOS 用 SwiftUI、Windows 用 WinUI 3 各写一个原生客户端，替换 Tauri + React 的"网页套壳"界面。
- 业务逻辑只保留在 Python 里一份。两个原生客户端只负责展示和交互，**不重写**时间冲突、持有推断、评分匹配、日志解析这类规则。
- Tauri 版在 ng 功能对齐之前继续可用，两者读写同一份数据目录。

## 分层

```
┌──────────────────────┐   ┌──────────────────────┐
│ ng/macos  (SwiftUI)  │   │ ng/windows (WinUI 3) │   原生 UI：窗口、菜单、托盘、通知、钥匙串提示
└──────────┬───────────┘   └──────────┬───────────┘
           │  stdio 上的按行 JSON（协议 v1）    │
           └───────────────┬──────────────────┘
                 ┌─────────▼─────────┐
                 │ ng_service.py      │  常驻进程：RPC 分发、子进程管理、状态文件监听
                 │ ng_logic.py        │  纯函数：冲突标记、加课合并、日志解析、失败提示
                 └─────────┬─────────┘
                           │ 复用
     gui_backend.py（快照/保存） config.py  monitor.py  bootstrap.py  timetable.py …
```

与 Tauri 版的区别：
- Tauri 每次调用都新起一个 `gui_backend.py` 进程，ng 只起一个常驻 `ng_service.py`。监控、抓取这些子进程也由它管理，客户端只需维护这一条管道。
- 客户端不再定时轮询：状态文件（state.json、catalog.json 等）变化时由服务端推送 `state.changed`。
- `courseLogic.ts` 里的冲突标记、加课提示、日志解析、抓取失败提示都搬到 `ng_logic.py`，客户端通过 RPC 取结果。

## 协议 v1

启动：源码模式下是 `python ng_service.py`；打包后是 `sjtu-backend ng_service.py`（由 `backend_entry.py` 分发）。
环境变量沿用现有约定：`SJTU_MONITOR_DATA_DIR`、`SJTU_MONITOR_RELEASE`。

stdin 和 stdout 上都是每行一个 UTF-8 JSON 对象。stdout 只用来走协议，Python 里 `print` 的内容会被重定向到 stderr。

| 方向 | 形态 |
|---|---|
| 客户端 → 服务 | `{"id": 1, "method": "snapshot", "params": {}}` |
| 服务 → 客户端（成功） | `{"id": 1, "result": {...}}` |
| 服务 → 客户端（失败） | `{"id": 1, "error": {"code": "invalid_params", "message": "..."}}` |
| 服务 → 客户端（事件） | `{"event": "process.output", "data": {...}}` |

stdin 关闭时，服务端会结束自己启动的所有子进程，然后退出。

### 方法

| method | params | result |
|---|---|---|
| `hello` | – | `{protocol, version, release_mode, data_dir, platform}` |
| `snapshot` | – | 与 Tauri 版 `Snapshot` 相同（不含 `logs`），并增加 `groups[].conflicts`、`running` |
| `groups.evaluate` | `{groups:[{name,is_pe,priority}]}` | 针对**未保存**的方案给出 `[{name, held, held_label, conflicts, conflict_count}]` |
| `groups.add_courses` | `{priority, added}` | `{priority, added, warning}`：按"已选放末尾"合并，并给出冲突提示文案 |
| `groups.save` | `{groups:{name:{is_pe,priority}}}` | 同 `gui_backend.save_groups` |
| `settings.save` | SettingsPayload | `{ok}` |
| `settings.test_email` | – | `{ok, mail_to}` |
| `onboarding.complete` | – | `{ok}` |
| `term.switch` | `{xkxnm, xkxqm}` | `{ok, active_term}` |
| `autoswap.set` | `{enabled, dry_run}` | `{ok}` |
| `process.start` | `{task, debug?}` | `{ok, running}` |
| `process.stop` | `{task}` | `{ok, running}` |
| `process.list` | – | `{running}` |
| `logs.query` | `{level?, query?, limit?}` | `{entries:[{time,level,source,message}], counts}` |

`task` 只接受以下几种，客户端不能传任意脚本：

| task | 命令 |
|---|---|
| `once` | `monitor.py --once` |
| `monitor` | `monitor.py` |
| `bootstrap` | `bootstrap.py` |
| `onboarding-sync` | `bootstrap.py --adopt-site-term`（运行标签仍为 `bootstrap`） |
| `ratings-all` | `bootstrap.py --fetch-ratings-all` |
| `detect-term` | `bootstrap.py --detect-term` |

### 事件

| event | data |
|---|---|
| `process.output` | `{task, entry:{time,level,source,message}}` |
| `process.exited` | `{task, code, notice?:{title,message}, status?}`：抓取类进程失败时带 `notice` |
| `processes` | `{running:[...]}`：运行中的任务集合有变化时推送 |
| `state.changed` | `{files:[...]}`：状态文件的 mtime 变化时推送，客户端据此重新取快照 |

## 原生客户端要做到的"原生感"
- **macOS**：`NavigationSplitView` 侧栏配毛玻璃；课程目录用 `Table`，支持列排序和多选；详情放在 `.inspector`；优先级列表用 `List` 拖拽排序；`Settings` 场景（⌘,）；用 `MenuBarExtra` 显示监控状态；`UserNotifications` 发通知；有未保存修改时标记 `documentEdited`；工具栏配搜索框。
- **Windows**：`NavigationView` 加 Mica 背景；课程目录用 `ListView` 加列头；详情用分栏；`ContentDialog` 做确认；托盘图标（H.NotifyIcon）；`AppNotificationManager` 发通知；标题栏使用系统主题色。
- 两端都支持：关窗后监控继续在托盘/菜单栏运行，退出时才结束服务进程；浅色/深色跟随系统，可在设置里覆盖。

## 分期
1. **服务层**：`ng_logic.py` + `ng_service.py` + 离线单测（`test_ng_service.py`）。
2. **macOS MVP**：总览、课程方案、自动换课、快照、日志、设置、首次引导，功能与 Tauri 版对齐。
3. **Windows MVP**：同一套功能，通过 `ssh winpc-ts` 编译和冒烟测试。
4. **打包**：`sjtu-backend` sidecar 放进 `.app` 和 Windows 安装包；CI 增加 Swift 和 .NET 构建。
5. **收尾**：通知改由原生客户端负责（`monitor.py` 在 ng 模式下只输出结构化事件），菜单栏/托盘快捷操作。
