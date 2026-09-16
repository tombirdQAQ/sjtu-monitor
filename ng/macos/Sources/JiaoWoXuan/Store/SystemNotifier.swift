import AppKit
import UserNotifications

/// 系统通知。只在应用不在前台时发送(前台已有弹窗),且必须以 .app 形式运行:
/// `swift run` 得到的裸可执行文件没有 bundle identifier,UNUserNotificationCenter 会直接崩溃。
enum SystemNotifier {
    @MainActor
    static func post(title: String, body: String) {
        guard Bundle.main.bundleIdentifier != nil, !NSApp.isActive else { return }
        let center = UNUserNotificationCenter.current()
        center.requestAuthorization(options: [.alert, .sound]) { granted, _ in
            guard granted else { return }
            let content = UNMutableNotificationContent()
            content.title = title
            content.body = body
            content.sound = .default
            center.add(UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil))
        }
    }
}
