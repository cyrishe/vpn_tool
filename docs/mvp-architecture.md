# Regional VPN MVP 架构

## 1. 当前目标

第一阶段优先验证产品核心闭环：

1. 用户登录并获得订阅权限。
2. 客户端注册自己的设备和隧道公钥。
3. 客户端只看到套餐允许的逻辑地区。
4. 用户选择地区，控制面准备新配置。
5. 客户端验证并应用配置。
6. 成功后提交切换，失败则恢复最后一次可用配置。

云服务器竞价采购、自动扩缩容、真实 WireGuard 网关 Agent 和支付不属于第一
阶段，但接口边界需要提前保留。

## 2. 系统边界

```text
macOS Client
  ├── Account Session
  ├── Region Picker
  ├── Switch Coordinator
  └── TunnelDriver
          │
          │ HTTPS control API
          ▼
Control Plane
  ├── Auth & Subscription
  ├── Device Registry
  ├── Logical Region Catalog
  ├── Gateway Scheduler
  └── Switch State Machine
          │
          │ desired-state reconciliation (later)
          ▼
Regional Gateway Agent
  ├── WireGuard peer reconciliation
  ├── health and capacity
  └── usage counters
```

控制面不在用户流量路径中。控制面临时不可用时，现有 VPN 连接必须继续工作；
只暂停登录、新设备注册和地区切换。

## 3. 核心不变量

### 权限

- 服务端从访问令牌确定用户，不接受客户端传入 `user_id`。
- 所有设备操作必须验证设备归当前用户所有。
- 地区权限由有效订阅和套餐地区映射共同确定。
- 客户端隐藏按钮不等于权限控制。

### 密钥

- 隧道私钥只在客户端生成和保存。
- 控制面只保存设备公钥。
- 云厂商密钥永远不进入客户端或地区网关。

### 切换

- 新配置准备完成前，旧 assignment 保持 `active`。
- 客户端确认成功后，新 assignment 才变为 `active`。
- 客户端确认失败时，新 assignment 释放，旧 assignment 不变。
- 所有切换请求必须携带 `Idempotency-Key`。
- 单个 Peer 更新不得重启整个 WireGuard 接口。

公网出口变化后，既有 TCP、QUIC 和 WebSocket 连接可能重新建立。MVP 的保证是
切换失败自动回退、不造成持续断网、且不影响同网关上的其他用户，而不是保证
所有现存连接跨公网 IP 无损迁移。

## 4. 逻辑地区与实际节点

客户端只消费逻辑地区：

```text
Shanghai
Beijing
Guangdong
```

服务端维护实际映射：

```text
logical_region
  └── gateway_nodes[]
        ├── provider
        ├── cloud_region
        ├── endpoint
        ├── status
        ├── capacity
        └── current_peers
```

节点状态：

```text
provisioning -> verifying -> ready -> draining -> unhealthy -> terminated
```

只有 `ready` 节点接收新 assignment。调度器优先选择健康且剩余容量最多的节点；
云厂商调度以后只负责补充和回收 `gateway_nodes`，不改变客户端协议。

## 5. 切换状态机

```text
POST /v1/devices/{device_id}/switches
  -> prepared
      ├── POST /v1/switches/{id}/confirm success=true
      │     -> committed
      └── POST /v1/switches/{id}/confirm success=false
            -> rolled_back
```

准备阶段：

1. 验证用户、设备、订阅和目标地区。
2. 复用相同 `Idempotency-Key` 的既有操作。
3. 选择一个 `ready` 网关。
4. 创建候选 Peer assignment。
5. 网关确认 Peer 已准备好。
6. 返回不含客户端私钥的隧道 profile。

MVP 中第 5 步由本地模拟网关立即确认。接入真实 Agent 后，该操作变为异步，
客户端通过 operation ID 轮询或长连接等待 `prepared`。

确认阶段：

- `success=true`：候选 assignment 激活，旧 assignment 释放。
- `success=false`：候选 assignment 释放，旧 assignment 保持激活。
- 重复确认返回同一最终结果。

## 6. API 契约

| Method | Path | 说明 |
| --- | --- | --- |
| `GET` | `/healthz` | 进程和数据库健康 |
| `POST` | `/v1/auth/login` | 登录并签发不透明访问令牌 |
| `GET` | `/v1/me` | 当前账户 |
| `GET` | `/v1/regions` | 当前订阅允许的逻辑地区 |
| `GET` | `/v1/devices` | 当前用户设备 |
| `POST` | `/v1/devices` | 幂等注册设备 |
| `POST` | `/v1/devices/{id}/switches` | 准备地区切换 |
| `POST` | `/v1/switches/{id}/confirm` | 提交或回滚切换 |

错误统一返回：

```json
{
  "error": {
    "code": "region_not_in_plan",
    "message": "The active subscription does not include this region."
  },
  "request_id": "..."
}
```

## 7. 数据模型

第一版表：

- `users`
- `access_tokens`
- `plans`
- `subscriptions`
- `logical_regions`
- `plan_regions`
- `devices`
- `gateway_nodes`
- `peer_assignments`
- `switch_operations`

后续表：

- `usage_samples`
- `gateway_heartbeats`
- `audit_logs`
- `provisioning_operations`
- `payment_orders`

开发环境使用 SQLite 和 `create_all`。进入共享测试环境前切换 PostgreSQL，并使用
Alembic 管理显式迁移。

## 8. macOS 客户端

客户端分为三层：

```text
SwiftUI UI
  -> AppModel / switch coordinator
      -> ControlPlaneAPI
      -> TunnelDriving
```

`TunnelDriving` 是稳定边界：

```text
publicKey()
prepare(profile)
activatePrepared()
restorePrevious()
disconnect()
```

当前 `MockTunnelDriver` 只模拟准备、激活和恢复，不修改路由。下一阶段用
WireGuardKit + Network Extension 实现同一协议，因此账户、地区列表和切换协调器
不需要重写。

正式客户端首次连接仍需用户确认 macOS 系统 VPN 权限；这个系统授权不能绕过，
但用户不需要执行 Shell、修改转发、DNS 或防火墙。

## 9. 分阶段实现

### M1：控制面闭环（当前）

- 本地账号登录
- 订阅地区
- 设备注册
- 两阶段切换
- macOS Mock TunnelDriver
- 后端与 Swift 单元测试

### M2：真实 macOS VPN

- Xcode App 与 Packet Tunnel Extension
- WireGuardKit
- Keychain 中的真实 WireGuard 私钥
- 新节点预检、原子切换和失败恢复
- VPN 冲突提示

### M3：真实地区网关

- Linux WireGuard bootstrap
- Gateway Agent 注册和拉取 desired state
- 增量 Peer 更新
- 健康、容量和流量上报

### M4：生产控制面

- PostgreSQL 与 Alembic
- 短信登录、支付、订阅续费
- 管理后台、审计和风控
- 限流、监控、备份和恢复

### M5：云资源供应

- 腾讯云/阿里云 provider adapter
- 按量与竞价混合节点池
- EIP、回收通知、draining 和自动替换

## 10. 上线阻塞项

本项目面向中国大陆公开用户前，必须单独确认：

- 增值电信业务许可或持牌合作模式。
- 国内公网 VPN 出口业务是否符合可经营范围。
- ICP、隐私政策、用户协议和日志留存要求。
- 短信、支付、实名和反滥用流程。
- Apple Network Extension 权限及 App 分发审核。

这些问题不阻塞内部技术 PoC，但阻塞收费和公开发布。
