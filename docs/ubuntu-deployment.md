# 固定 Ubuntu 部署

## 当前部署（2026-11-11）

服务器：`ubuntu@101.34.21.167`。目前在同一台机器上运行中心和唯一的上海出口。
客户端直接请求 `https://101.34.21.167`；中心和网关均不依赖 Mac 或 SSH 转发。
旧中心不可达，本次从本地联调快照恢复账号与地域配置，并轮换了节点凭证。

| 项目 | 固定位置 |
| --- | --- |
| 源码与 Python 虚拟环境 | `/opt/regional-vpn`、`/opt/regional-vpn/.venv` |
| 中心入口 | `control_plane.ubuntu:app` |
| 数据库 | `/var/lib/regional-vpn/control.db`（SQLite） |
| 数据库备份 | `/var/backups/regional-vpn/control-*.db` |
| TLS 证书与密钥 | `/etc/regional-vpn/control.crt`、`control.key` |
| 网关凭证 | `/etc/regional-vpn/gateway.json` |
| WireGuard 接口 | `wg-regional`，UDP 51820 |
| 中心 API | HTTPS TCP 443 |

数据库已迁入现有账号、地域、套餐、设备、节点及凭证。服务端不创建演示账号。
SQLite 为固定单进程部署，当前不引入 PostgreSQL、Docker 或多环境配置。
中心以专用 regionalvpn 系统用户运行，网关 Agent 独立持有网络配置能力。

## 常用操作

```bash
sudo systemctl status regional-control regional-gateway
sudo journalctl -u regional-control -n 50 --no-pager
sudo journalctl -u regional-gateway -n 50 --no-pager
sudo systemctl restart regional-control
sudo systemctl restart regional-gateway
```

这两个服务、WireGuard、防火墙及备份 timer 均已设置开机启动。
中心重启后数据仍从同一数据库加载，网关会自动重试连接。

管理工具固定操作同一个数据库，新增地域/节点不需要改服务配置：

```bash
sudo -u regionalvpn regional-vpn-admin region beijing 北京 --province CN-BJ
sudo -u regionalvpn regional-vpn-admin gateway beijing-01 --region beijing \
  --endpoint NODE_IP:51820 --public-key NODE_PUBLIC_KEY \
  --credential-out /var/lib/regional-vpn/beijing-01.json
```

注册成功后仍需把对应节点凭证安全交给新节点，并启动 Agent。
不要把节点 token、数据库或 WireGuard 私钥放入 Git。

### 地域节点更换

中心保留地域名称和用户权限；更换服务器时，在原地域注册一个**新节点**。
在新机器运行 `scripts/setup-wireguard-gateway.sh`，开放入站 UDP 51820，
记录它的公网 IPv4 与 WireGuard 公钥。用中心的 `gateway` 命令登记节点、生成凭证。
在新机器的 `/opt/regional-vpn/service` 安装 `gateway_agent`、`control_plane` 和依赖，
将凭证及中心公开证书分别安装为 `/etc/regional-vpn/gateway.json`（0600）和 `control.crt`。
安装 `service/gateway_agent/regional-gateway.service`，在 `/etc/regional-vpn/agent.env`
设置 `VPN_CONTROL_URL=https://中心地址`。跨机网关使用这个单元；同机网关使用
`deploy/ubuntu/regional-gateway.service`。

```bash
sudo -u regionalvpn regional-vpn-admin nodes
sudo -u regionalvpn regional-vpn-admin node-state NODE_NAME online
sudo -u regionalvpn regional-vpn-admin node-state OLD_NODE drain
sudo -u regionalvpn regional-vpn-admin node-state OLD_NODE retire
```

新节点心跳后处于 `verifying`；先检查 UDP 与出口条件，再执行 `online`，它才会接单。
`drain` 停止派发新连接，保留已分配的连接；待连接清空后 `retire` 拒绝旧节点凭证、
释放剩余分配。意外失联约 30 秒后不接新连接，用户可重新连接同地域其他节点。
首版由管理员触发上下线，不自动采购或迁移现有会话。

### 中心机器更换

在新 Ubuntu 部署相同模板，把 SQLite 一致性备份和需保留的节点配置安全迁移。
切换前停止旧中心写入，避免双写。节点 Agent 改为新中心地址；客户端只改中心
地址与证书，重新构建即可，不改地域或节点代码。将来绑定稳定域名和受信证书后，
迁中心可通过 DNS 切换，免去重新分发 IP 证书。

## 客户端

macOS 原生联调包用 `bash scripts/build-macos-pilot.sh 101.34.21.167` 构建，
证书从 `.runtime/poc/control-101.34.21.167.crt` 读取。App 提供账号登录、
已开通地域、连接、断开和实际 IPv4 出口；本机可点「使用联调账号」，凭证不打进包。
此包使用 AppKit、Python 3 和本机已安装的 `wg-quick` / `wireguard-go`。
需要改路由时 macOS 弹出管理员授权；不是已签发 Network Extension 的分发版。

命令行客户端也已指向 Ubuntu HTTPS，并校验证书：

```bash
cd /Users/chenghe/work/vpn_tool-dev
bash scripts/poc-client.sh regions
bash scripts/poc-client.sh connect
bash scripts/poc-client.sh disconnect
```

用户密码、客户端私钥及信任证书位于 `.runtime/poc/`，不上传 Git。
客户端仍是命令行联调版，connect/disconnect 的系统操作会请求 sudo。
当前证书是带服务器 IP 的自签证书，有效期一年；客户端显式信任此证书，
未关闭 TLS 验证。正式客户端分发和证书轮换需后续处理。

## 数据库备份与恢复

每天北京时间 11:15 左右自动在线备份，备份文件仅 regionalvpn 用户可读。
备份使用 SQLite backup API，生成后执行 integrity_check。暂不自动删除历史备份。

```bash
sudo systemctl start regional-backup.service
sudo systemctl list-timers regional-backup.timer
sudo ls -lh /var/backups/regional-vpn
```

已验证将备份恢复到独立内存数据库，完整性正常，用户和节点记录保留。
需要真实恢复时先停止中心及网关，把现有数据库整体移到安全备份目录，
再将选定快照恢复为固定路径并设置 regionalvpn:regionalvpn、0600 权限，最后启动服务。
恢复操作会回退数据，必须明确选择快照；本轮未覆盖线上数据库进行恢复演练。

## 验证记录与范围

- HTTPS 健康检查、账号登录、地域列表正常。
- 关闭旧 Mac 中心与 SSH 反向隧道后，远端仍能同步。
- 真实 Peer 下发、确认及断开撤销通过。
- 中心服务重启、备份生成与独立恢复校验通过。
- 在新服务器验证了 HTTPS、实际 Peer 下发与撤销、UDP 入站及原生 App 登录。
- App 中真正启用系统隧道需要本机管理员授权；IPv6 完整接管和自动切换仍待完善。

部署模板在 `deploy/ubuntu/`。`install-control.sh` 准备系统用户、证书与服务单元，
不会自动复制数据库或覆盖现有业务数据；首次部署须单独完成数据初始化/迁移。
