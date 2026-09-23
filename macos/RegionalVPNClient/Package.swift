// swift-tools-version: 6.0

import PackageDescription

let package = Package(
    name: "RegionalVPNClient",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .executable(name: "RegionalVPNClient", targets: ["RegionalVPNClientApp"])
    ],
    targets: [
        .target(
            name: "RegionalVPNClientCore",
            linkerSettings: [
                .linkedFramework("Security")
            ]
        ),
        .executableTarget(
            name: "RegionalVPNClientApp",
            dependencies: ["RegionalVPNClientCore"]
        ),
        .testTarget(
            name: "RegionalVPNClientCoreTests",
            dependencies: ["RegionalVPNClientCore"]
        )
    ]
)

