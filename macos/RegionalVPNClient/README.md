# Regional VPN macOS Client

## 当前真实联调 App

`PilotApp/` 是本机可构建的 AppKit 客户端，复用真实 WireGuard 控制逻辑。
使用 [Ubuntu 部署文档](../../docs/ubuntu-deployment.md) 中的构建命令。
下方 SwiftUI 包是保留的模拟原型，不是当前联调 App。

SwiftUI macOS 客户端原型。当前真实连接本地控制面，但使用
`MockTunnelDriver`，不会创建 VPN、修改 DNS 或系统路由。

## 运行

先启动服务端：

```bash
cd ../../../service
uvicorn control_plane.app:app --reload
```

再启动客户端：

```bash
swift run RegionalVPNClient
```

默认控制面地址：

```text
http://127.0.0.1:8000
```

可覆盖：

```bash
VPN_CONTROL_PLANE_URL=http://127.0.0.1:8000 swift run RegionalVPNClient
```

演示账户：

```text
demo@example.com
demo-password
```

## 测试

```bash
swift test
```

## 下一阶段

将 `MockTunnelDriver` 替换为 Xcode App 中的 WireGuardKit 和 Packet Tunnel
Extension。该步骤需要 Apple Network Extension capability、签名和系统 VPN
授权，无法只靠 Swift Package 完成。

