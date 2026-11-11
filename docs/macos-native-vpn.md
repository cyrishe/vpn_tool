# macOS 系统 VPN 客户端

## 使用流程

1. 在 macOS 14 或更新版本上，将签名发布的「Regional VPN.app」放到「应用程序」目录。
2. 打开 App，登录现有账号，选择已开通的地域，点击「连接」。
3. 第一次按 macOS 提示允许网络系统扩展和添加 VPN 配置。系统可能要求管理员确认。
4. App 显示地域和验证过的出口 IP。之后在 App 中连接、断开或切换地域，复用这份系统 VPN 配置。重新启用配置或升级扩展时，系统可能再次要求批准。

发布包内含 WireGuard。用户只需安装 App。Xcode、XcodeGen 和 Go 是构建机依赖。

App 从中心查询账号可用地域，节点由中心分配。设备私钥保存在 macOS 钥匙串，启动时通过系统接口传给扩展。App 验证公网出口后向中心确认切换。验证失败会停止新隧道，有可恢复的原连接时会尝试恢复。

## 生成并签名

构建机需完整 Xcode、XcodeGen 和与项目固定的 WireGuard Apple 源码兼容的 Go 工具链。[WireGuard Apple 构建说明](https://git.zx2c4.com/wireguard-apple/about/)

使用系统信任的 HTTPS 中心时，直接生成项目。当前试运行中心使用自签名证书，生成时传入中心的**公开证书**。App 只对配置的中心主机和端口接受这张证书，并检查有效期。

```bash
bash scripts/prepare-macos-native.sh .runtime/poc/control-101.34.21.167.crt
open macos/RegionalVPNClient/Native/RegionalVPNNative.xcodeproj
```

- 选择 `RegionalVPN` scheme，配置 App 和系统扩展的签名 Team。两个目标使用同一 Team，App ID 和配置描述文件需匹配 bundle ID 和对应的 Network Extension 权限。默认 bundle ID 为 `com.regionalvpn.client` 和 `com.regionalvpn.client.tunnel`。
- 构建脚本使用 Xcode 默认 DerivedData 内的 Swift Package checkout。中心换地址时通过构建设置 `REGIONAL_VPN_CONTROL_URL` 指定 HTTPS URL。私有证书变更时，用新公开证书重新生成项目。
- 对外分发时，在有对应权限的 Apple Developer Team 下以 Developer ID 签名并公证，然后将签名包交给用户安装。[Apple 网络扩展分发说明](https://developer.apple.com/documentation/technotes/tn3134-network-extension-provider-deployment)

## 签名包验收

- 在尚未批准扩展的 Mac 上安装，完成系统提示并连接上海。确认 App 显示的出口 IP 与节点一致，连接后中心接口仍可用。
- 断开后确认出口恢复。连续连接、断开三次，并退出重开 App 再连接，确认系统配置复用且日常操作无管理员密码提示。
- 模拟节点不可达，确认 App 退出连接状态并恢复本机路由。连接期间检查 DNS 和 IPv6 路由。第二个地域接入后，验证切换及切换失败恢复。

当前已实现工程与客户端流程。完整 Xcode 构建、签名安装和上述系统级验收待在具备签名条件的 Mac 上完成。
