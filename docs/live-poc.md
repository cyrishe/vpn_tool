# 真实网关联调（2026-11-06）

> 历史拓扑记录：中心已迁到 Ubuntu，以下 Mac 中心与 SSH 转发不再使用。
> 当前配置见 [固定 Ubuntu 部署](ubuntu-deployment.md)，客户端验收状态见 [项目交接](handover.md)。

## 部署状态

- 中心：本机 127.0.0.1:8018，独立生产模式数据库，未加载 mock 节点。
- 地域网关：1.15.138.37，wg-regional，UDP 51820。
- 远端服务：regional-gateway、wg-quick@wg-regional、regional-firewall。
- Agent 经 SSH 反向隧道访问远端回环 18018，再到本机中心 8018；无公网管理端口。
- 凭证、客户端密钥与数据库位于 .runtime/poc/，已排除 Git。
- 网关服务会随系统启动；本机中心和 SSH 隧道须保持运行。

此为联调拓扑，正式部署时中心应在固定服务器通过 HTTPS 提供服务。

## 已验证

实际注册网关 -> 用户获得上海地域 -> 中心调度 -> Agent 在 Linux WireGuard 中
安装真实设备公钥 -> 中心收到确认并返回 profile -> 用户断开 -> 远端 Peer 被移除。
执行记录保存在 .runtime/poc/control-check.json，不包含密码或私钥。

本机 WireGuard 工具已安装。系统隧道尚未启用，本机出口变化未验收。
UDP 探测从本机和另一台云服务器发出，目标未抓到报文；须确认云安全组放行
入站 UDP 51820，再复测。也可能存在上游或本机网络限制。

## 本机操作

```bash
cd /Users/chenghe/work/vpn_tool-dev
bash scripts/poc-client.sh regions
bash scripts/poc-client.sh connect
```

connect 在当前终端请求 sudo，以创建系统隧道及调整路由/DNS。
客户端本地生成私钥，只把公钥注册给中心；选择地域后等待远端 Agent 确认。
启用 wg-quick 后用无代理 curl 对比公网出口，预期为 1.15.138.37。
检测失败会尝试断开并恢复路由；服务端分配同步释放。
这项 IP 验证针对系统直连流量；本机已有 127.0.0.1:7890 系统代理，浏览器如仍
使用代理，显示的 IP 可能不同，验证前需在代理应用中关闭系统代理。

```bash
bash scripts/poc-client.sh disconnect
```

disconnect 调用 wg-quick 恢复路由和 DNS，再释放中心分配。
若中心不可用，可先执行以下本地恢复（中心授权还会受短租约限制）：

```bash
sudo /opt/homebrew/bin/bash /opt/homebrew/bin/wg-quick down \
  /Users/chenghe/work/vpn_tool-dev/.runtime/poc/client/regionvpn.conf
```

## 重启联调依赖

```bash
cd /Users/chenghe/work/vpn_tool-dev/service
VPN_ENVIRONMENT=production \
VPN_DATABASE_URL=sqlite:////Users/chenghe/work/vpn_tool-dev/.runtime/poc/control.db \
python3 -m uvicorn control_plane.app:app --host 127.0.0.1 --port 8018
```

SSH 隧道应只启动一份，先检查：

```bash
ssh -S /Users/chenghe/work/vpn_tool-dev/.runtime/poc/ssh.sock -O check ubuntu@1.15.138.37
```

若已断开，再启动：

```bash
ssh -fNT -M -S /Users/chenghe/work/vpn_tool-dev/.runtime/poc/ssh.sock \
  -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
  -R 127.0.0.1:18018:127.0.0.1:8018 ubuntu@1.15.138.37
```
