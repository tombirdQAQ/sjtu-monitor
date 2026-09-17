import JiaoWoXuanCore
import SwiftUI

struct SettingsView: View {
    var body: some View {
        TabView {
            GeneralSettings()
                .tabItem { Label("通用", systemImage: "gearshape") }
            AccountSettings()
                .tabItem { Label("账号", systemImage: "person.badge.key") }
            MailSettings()
                .tabItem { Label("通知", systemImage: "envelope") }
        }
        .frame(width: 520)
        .fixedSize(horizontal: false, vertical: true)
    }
}

private struct GeneralSettings: View {
    @Environment(AppStore.self) private var store
    @AppStorage("appearance") private var appearance: Appearance = .system

    var body: some View {
        @Bindable var store = store
        Form {
            Picker("外观", selection: $appearance) {
                ForEach(Appearance.allCases) { Text($0.label).tag($0) }
            }
            .pickerStyle(.inline)
            Section("轮询") {
                Stepper(value: $store.settings.pollMin, in: 5...3600, step: 5) {
                    LabeledContent("最小间隔", value: "\(store.settings.pollMin) 秒")
                }
                Stepper(value: $store.settings.pollMax, in: 5...3600, step: 5) {
                    LabeledContent("最大间隔", value: "\(store.settings.pollMax) 秒")
                }
                Text("持续监控会在此区间内随机等待，降低固定频率请求特征。")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            if !store.releaseMode {
                Section("开发") {
                    Toggle("启动进程时输出调试日志", isOn: $store.debug)
                    if let hello = store.hello {
                        LabeledContent("数据目录") { Text(hello.dataDir).textSelection(.enabled).font(.caption) }
                    }
                }
            }
            SaveRow()
        }
        .formStyle(.grouped)
    }
}

private struct AccountSettings: View {
    @Environment(AppStore.self) private var store

    var body: some View {
        @Bindable var store = store
        Form {
            Section {
                TextField("JAccount", text: $store.settings.jaccountUser)
                SecureField("JAccount 密码", text: $store.settings.jaccountPass,
                            prompt: Text(store.settings.hasJaccountPass == true ? "已安全保存，留空不修改" : "未保存"))
            } header: {
                Text("交大 JAccount")
            }
            Section {
                SecureField("选课社区密码", text: $store.settings.coursePlusPassword,
                            prompt: Text(store.settings.hasCoursePlusPassword == true ? "已安全保存，留空不修改" : "未保存"))
            } header: {
                Text("选课社区 course.sjtu.plus")
            } footer: {
                Text("密码不回显，保存在系统安全存储（\(store.settings.secretBackend ?? "未知")）。")
            }
            SaveRow()
        }
        .formStyle(.grouped)
    }
}

private struct MailSettings: View {
    @Environment(AppStore.self) private var store

    var body: some View {
        @Bindable var store = store
        Form {
            Section {
                Toggle("启用邮件通知", isOn: $store.settings.emailEnabled)
                TextField("SMTP 服务器", text: $store.settings.smtpHost)
                TextField("端口", value: $store.settings.smtpPort, format: .number.grouping(.never))
                TextField("用户名", text: $store.settings.smtpUser)
                SecureField("密码", text: $store.settings.smtpPass, prompt: Text(smtpPrompt))
                TextField("发件人", text: $store.settings.mailFrom)
                TextField("收件人", text: $store.settings.mailTo)
            } footer: {
                Text("默认使用交大邮箱 mail.sjtu.edu.cn:465（SSL），账号为 jAccount@sjtu.edu.cn，密码复用 JAccount 密码；改用其他邮箱时覆盖对应字段即可。")
            }
            HStack {
                Button("保存并发送测试邮件") { Task { await store.sendTestEmail() } }
                    .disabled(store.busy)
                Spacer()
                SaveButton()
            }
        }
        .formStyle(.grouped)
    }

    private var smtpPrompt: String {
        guard store.settings.hasSmtpPass == true else { return "未保存" }
        return store.settings.smtpPassFallback == true ? "默认复用 JAccount 密码，可单独设置" : "已安全保存，留空不修改"
    }
}

private struct SaveRow: View {
    var body: some View {
        HStack {
            Spacer()
            SaveButton()
        }
    }
}

private struct SaveButton: View {
    @Environment(AppStore.self) private var store

    var body: some View {
        Button("保存设置") { Task { await store.saveSettings() } }
            .keyboardShortcut(.defaultAction)
            .disabled(!store.settingsDirty || store.busy || store.phase != .ready)
    }
}
