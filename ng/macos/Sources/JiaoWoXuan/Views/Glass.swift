import SwiftUI

// Liquid Glass(macOS 26+)与旧系统材质效果的兼容层。
// 部署目标仍是 macOS 14:新 API 一律经 #available 判断,旧系统回落到 Material。

extension View {
    /// 玻璃卡片。tint 为 nil 时是中性玻璃;interactive 用于可点击的卡片(按下有液态反馈)。
    @ViewBuilder
    func glassCard(cornerRadius: CGFloat = 18, tint: Color? = nil, interactive: Bool = false) -> some View {
        if #available(macOS 26, *) {
            glassEffect(.regular.tint(tint).interactive(interactive), in: .rect(cornerRadius: cornerRadius))
        } else {
            background {
                RoundedRectangle(cornerRadius: cornerRadius)
                    .fill(.regularMaterial)
                    .overlay {
                        if let tint {
                            RoundedRectangle(cornerRadius: cornerRadius).fill(tint.opacity(0.18))
                        }
                    }
                    .overlay(RoundedRectangle(cornerRadius: cornerRadius).strokeBorder(.separator.opacity(0.6)))
            }
        }
    }

    /// 玻璃胶囊(方案标签、状态指示)。
    @ViewBuilder
    func glassCapsule(tint: Color? = nil, interactive: Bool = false) -> some View {
        if #available(macOS 26, *) {
            glassEffect(.regular.tint(tint).interactive(interactive), in: .capsule)
        } else {
            background(Capsule().fill(tint.map { AnyShapeStyle($0.opacity(0.85)) } ?? AnyShapeStyle(.regularMaterial)))
        }
    }

    /// 玻璃按钮;prominent 为强调色主操作。
    @ViewBuilder
    func glassButton(prominent: Bool = false) -> some View {
        if #available(macOS 26, *) {
            if prominent {
                buttonStyle(.glassProminent)
            } else {
                buttonStyle(.glass)
            }
        } else if prominent {
            buttonStyle(.borderedProminent)
        } else {
            buttonStyle(.bordered)
        }
    }
}

/// 多个相邻玻璃元素放进同一个容器,系统会把它们作为一组渲染(靠近时融合、共享采样)。
struct GlassGroup<Content: View>: View {
    var spacing: CGFloat = 12
    @ViewBuilder var content: Content

    var body: some View {
        if #available(macOS 26, *) {
            GlassEffectContainer(spacing: spacing) { content }
        } else {
            content
        }
    }
}

/// 页面底层的柔和彩色氛围背景,给玻璃提供可折射的内容;深浅色自动适配。
struct AmbientBackground: View {
    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        let strength = colorScheme == .dark ? 0.32 : 0.22
        GeometryReader { proxy in
            let size = proxy.size
            ZStack {
                Circle()
                    .fill(Color.accentColor.opacity(strength))
                    .frame(width: size.width * 0.7)
                    .blur(radius: 120)
                    .offset(x: -size.width * 0.3, y: -size.height * 0.35)
                Circle()
                    .fill(Color.purple.opacity(strength * 0.8))
                    .frame(width: size.width * 0.55)
                    .blur(radius: 130)
                    .offset(x: size.width * 0.35, y: -size.height * 0.1)
                Circle()
                    .fill(Color.teal.opacity(strength * 0.7))
                    .frame(width: size.width * 0.6)
                    .blur(radius: 140)
                    .offset(x: size.width * 0.05, y: size.height * 0.45)
            }
            .frame(width: size.width, height: size.height)
        }
        .ignoresSafeArea()
        .allowsHitTesting(false)
    }
}
