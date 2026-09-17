import JiaoWoXuanCore
import SwiftUI

struct OnboardingView: View {
    @Environment(AppStore.self) private var store

    private let steps = ["保存账号", "同步课程", "配置方案"]

    var body: some View {
        @Bindable var store = store
        VStack(spacing: 0) {
            Spacer(minLength: 24)
            VStack(alignment: .leading, spacing: 22) {
                HStack(spacing: 12) {
                    Image(systemName: "graduationcap.fill")
                        .font(.system(size: 34))
                        .foregroundStyle(Color.accentColor)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("欢迎使用交我选").font(.title.weight(.semibold))
                        Text("完成基础设置后再创建自己的监控方案").foregroundStyle(.secondary)
                    }
                }
                HStack(spacing: 0) {
                    ForEach(Array(steps.enumerated()), id: \.offset) { index, label in
                        let reached = store.onboardingStep >= index + 1
                        HStack(spacing: 6) {
                            Image(systemName: reached ? "\(index + 1).circle.fill" : "\(index + 1).circle")
                                .foregroundStyle(reached ? Color.accentColor : Color.secondary)
                            Text(label).foregroundStyle(reached ? .primary : .secondary)
                        }
                        if index < steps.count - 1 {
                            Rectangle().fill(.separator).frame(height: 1).padding(.horizontal, 10)
                        }
                    }
                }
                Divider()
                switch store.onboardingStep {
                case 1: account
                case 2: sync
                default: finish
                }
                Text(store.status)
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            .padding(32)
            .frame(width: 580)
            .glassCard(cornerRadius: 28)
            Spacer(minLength: 24)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background { AmbientBackground() }
    }

    private var account: some View {
        @Bindable var store = store
        return VStack(alignment: .leading, spacing: 14) {
            Text("连接 JAccount").font(.title2.weight(.semibold))
            Text("凭据保存在系统安全存储（\(store.settings.secretBackend ?? "未知")）中。本步骤不会发起网络请求。")
                .foregroundStyle(.secondary)
            Form {
                TextField("JAccount", text: $store.settings.jaccountUser)
                SecureField("密码", text: $store.settings.jaccountPass,
                            prompt: Text(store.settings.hasJaccountPass == true ? "已安全保存，留空不修改" : "请输入密码"))
            }
            .formStyle(.grouped)
            .scrollDisabled(true)
            .frame(height: 110)
            Text("本应用面向上海交通大学在校师生，需使用学校统一分配的 JAccount 登录（jaccount.sjtu.edu.cn）。非交大用户可点击“以演示模式预览”查看示例数据与全部界面。")
                .font(.callout)
                .foregroundStyle(.secondary)
            HStack {
                Button {
                    Task { await store.enterDemo() }
                } label: {
                    Label("以演示模式预览", systemImage: "eye")
                }
                .glassButton()
                .help("无需 JAccount 与校园网，使用离线示例数据体验全部界面")
                Spacer()
                Button("保存并继续") { Task { await store.saveOnboardingAccount() } }
                    .keyboardShortcut(.defaultAction)
                    .glassButton(prominent: true)
                    .disabled(store.busy)
            }
        }
    }

    private var sync: some View {
        let syncing = store.running.contains("bootstrap")
        return VStack(alignment: .leading, spacing: 14) {
            Text("同步课程目录").font(.title2.weight(.semibold))
            Text("只有点击下方按钮后才会登录教务系统，获取用户信息、全量课程和当前已选课程。同步失败时可返回修改账号后重试，不会自动启动监控或换课。")
                .foregroundStyle(.secondary)
            if !store.bootstrapLines.isEmpty {
                VStack(alignment: .leading, spacing: 2) {
                    ForEach(Array(store.bootstrapLines.enumerated()), id: \.offset) { _, line in
                        Text(line).lineLimit(1)
                    }
                }
                .font(.system(.caption, design: .monospaced))
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(10)
                .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 8))
            }
            HStack {
                Button("返回修改账号") { store.onboardingStep = 1 }
                    .disabled(syncing)
                Spacer()
                if syncing { ProgressView().controlSize(.small) }
                Button(syncing ? "同步中…" : "开始同步课程") { store.run("bootstrap", adoptSiteTerm: true) }
                    .keyboardShortcut(.defaultAction)
                    .glassButton(prominent: true)
                    .disabled(syncing)
            }
        }
    }

    private var finish: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("创建自己的选课方案").font(.title2.weight(.semibold))
            Text("进入课程工作台后，新建方案并按从高到低排列教学班，当前已选班放在末尾。")
                .foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 8) {
                Label("双击或右键课程可加入当前方案", systemImage: "checkmark")
                Label("自动换课只向更高优先级升级，不会降级", systemImage: "checkmark")
                Label("自动换课默认关闭，需在完成方案后手动启用", systemImage: "checkmark")
            }
            HStack {
                Spacer()
                Button("进入课程方案") { Task { await store.finishOnboarding() } }
                    .keyboardShortcut(.defaultAction)
                    .glassButton(prominent: true)
                    .disabled(store.busy)
            }
        }
    }
}
