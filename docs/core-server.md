# 核心服务端：中心控制面与地域网关

当前运行配置已固定为 Ubuntu，见 [Ubuntu 部署](ubuntu-deployment.md)。
下文中的环境变量示例为早期开发接口说明，当前服务器直接使用固定入口和 systemd 单元。

## 架构

中心控制面运行在一台独立机器：账号、地域授权、网关注册、调度、配置下发。
各地服务器作为网关，运行 WireGuard 和 Gateway Agent，主动向中心同步。
客户端选择逻辑地域，中心按健康和剩余容量分配节点。流量从客户端直达地域网关。
网页仅为开发预览；正式客户端需要系统 VPN 能力。

## 当前实现与验证边界

已实现节点独立凭证、地域绑定、节点心跳、设备分配、网关应用确认、设备地址分配、
订阅到期撤权、断开释放、失败撤回、短期租约。真实网关的 profile 在 Agent 确认前
为 null，客户端通过 GET /v1/switches/{id} 轮询。status=prepared 不代表网关已就绪。
Agent 使用 wg set 增量配置专用接口，不重启其他用户的隧道。

测试使用合成公钥和替代命令执行器，验证控制协议与命令构造；尚未在 Linux
真实内核、云安全组、NAT 和原生客户端上完成端到端出口验证。
同步成功表示 Agent 可达；不等于公网 UDP 端口、出口质量已验证。

## 中心端操作

在 service 目录使用同一虚拟环境和同一数据库配置。真实部署设置
VPN_ENVIRONMENT=production，使用独立数据库，不加载开发演示节点；中心 API
置于 HTTPS 反向代理后。数据库迁移、多实例并发、速率限制和管理审计仍待完善。

```bash
export VPN_ENVIRONMENT=production
export VPN_DATABASE_URL=sqlite:////var/lib/regional-vpn/control.db
python -m control_plane.manage region shanghai 上海 --province CN-SH
python -m control_plane.manage gateway shanghai-01 --region shanghai \
  --endpoint SERVER_PUBLIC_IP:51820 --public-key SERVER_PUBLIC_KEY \
  --credential-out /secure/path/shanghai-01.json
python -m uvicorn control_plane.app:app --host 127.0.0.1 --port 8000
```

gateway 命令输出的凭证文件权限为 600。通过 SSH 安全传到对应网关的
/etc/regional-vpn/gateway.json，不发给用户。重复接入使用独立节点名。
节点首次同步时由 provisioning 进入 ready；停止心跳 30 秒后不再接受新调度。
同一地域增加第二台服务器重复执行 gateway 命令即可，用户不选节点。

```bash
# 在终端安全设置 VPN_NEW_USER_PASSWORD（不通过命令行参数传密码）。
python -m control_plane.manage user USER_EMAIL --regions shanghai --days 30
```

此命令创建测试用户和人工开通的地域订阅，不代表已实现支付。续期、停用等操作
命令尚待补充；现有订阅表的到期时间由同步协议强制执行。

## 地域端安装

专用 Ubuntu/Debian 测试节点运行 scripts/setup-wireguard-gateway.sh，生成独立
wg-regional 接口、公私钥、IPv4 NAT 和隔离防火墙规则；不会复用 Tailscale 接口。
执行前审阅脚本，确认 10.77.0.0/16 与本机网络不冲突，并在云安全组开放 UDP 51820。
首版 IPv6 不转发，正式客户端须把 IPv6 纳入隧道并验证无旁路泄漏。

将仓库安装在 /opt/regional-vpn，并创建 .venv，安装 service/requirements.txt。
将 agent.env 配置为 VPN_CONTROL_URL=https://YOUR_CONTROL_DOMAIN。
把 service/gateway_agent/regional-gateway.service 安装为系统服务，再启动。
该单元文件假定 Ubuntu 的 /usr/sbin/ip 路径，部署前核对。

Agent 独占 wg-regional 的 Peer 集合，会移除未获中心授权的 Peer。
首次启动先清除旧 Peer。中心失联后授权最长保留至当前租约失效（最多 30 秒，
加轮询/命令执行延迟）；systemd watchdog 在 Agent 卡死或崩溃后关闭接口。
因此必须按所附 unit 托管，单独运行 Python 不提供进程死亡后的清理保证。

## 后续验收

1. 新地域节点接入中心并被调度，用户看不到候选服务器清单。
2. 真客户端生成私钥、公钥，注册后等待 Agent 应用，再激活系统 VPN。
3. 测量实际 IPv4 出口、DNS、IPv6 阻断和用户隔离。
4. 验证断开、到期、节点离线和 Agent 被强制终止时的行为。
5. macOS Packet Tunnel / 手机系统 VPN 是下一模块，现有 MockTunnelDriver 不能作为真实客户端验收。

WireGuard 命令与公钥格式依据：[官方 Quick Start](https://www.wireguard.com/quickstart/)。
