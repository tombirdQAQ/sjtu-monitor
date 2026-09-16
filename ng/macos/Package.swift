// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "JiaoWoXuan",
    defaultLocalization: "zh-Hans",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "JiaoWoXuan", targets: ["JiaoWoXuan"]),
    ],
    targets: [
        .target(
            name: "JiaoWoXuanCore",
            path: "Sources/JiaoWoXuanCore",
            swiftSettings: [.swiftLanguageMode(.v5)]
        ),
        .executableTarget(
            name: "JiaoWoXuan",
            dependencies: ["JiaoWoXuanCore"],
            path: "Sources/JiaoWoXuan",
            swiftSettings: [.swiftLanguageMode(.v5)]
        ),
        .testTarget(
            name: "JiaoWoXuanCoreTests",
            dependencies: ["JiaoWoXuanCore"],
            path: "Tests/JiaoWoXuanCoreTests",
            swiftSettings: [.swiftLanguageMode(.v5)]
        ),
    ]
)
