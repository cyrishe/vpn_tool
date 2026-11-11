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

## 网页管理后台

管理页面在中心的 `/admin`，使用与现有客户端相同的 SQLite 数据库。
默认关闭。部署新版代码和 systemd 单元后，在中心生成独立的管理员访问密钥：

```bash
sudo sh -c 'umask 077; set -C; python3 -c "import secrets; print(\"VPN_ADMIN_TOKEN=vpn_admin_\" + secrets.token_urlsafe(32))" > /etc/regional-vpn/admin.env'
sudo systemctl daemon-reload
sudo systemctl restart regional-control
```

在 HTTPS 页面填写 `VPN_ADMIN_TOKEN` 的值。普通用户和节点的凭证无后台权限。
替换该文件中的密钥并重启中心可撤销旧密钥。操作记录可在
`journalctl -u regional-control` 中查找 `VPN admin action=`。

- **地域**可新增、修改显示名称和省级代码，也可停用。地域代码固定，客户端的权限仍跟随地域。停用会停止调度并释放该地域的现有连接。
- **节点**显示心跳时间、调度状态和分配数。「接入新 Ubuntu 节点」会提供部署包和两段 SSH 操作的命令。更换机器时，在同一地域登记新节点并上线，再排空、退役旧节点。用户继续选原地域。
- **账号开通**按邮箱查找账号，为新账号设置初始密码，选择地域和从今天起的有效天数。保存会替换当前授权。付款与开通在首版由管理员处理。

本地开发可设置同格式的 `VPN_ADMIN_TOKEN`，启动 `control_plane.app:app` 后访问
`http://127.0.0.1:8017/admin`。

### 启用自动接入

在中心完成一次配置后，后台「节点 → 自动接入 Ubuntu 节点」只需要节点公网 IPv4 和地域。
中心通过 SSH 安装 WireGuard，读取公钥，登记节点并启动 Agent。收到心跳后，在节点列表核验并上线。

1. 在中心准备一个由 `regionalvpn` 服务用户运行的 SSH 脚本，接收两个参数 `IP` 和远端命令。脚本应通过 SSH 执行该命令，原样传递 stdin 和 stdout，返回远端退出码，不分配终端。节点使用已有的授权方式，且该账户可以执行 `sudo -n`。中心需能访问节点 SSH，节点安全组需开放 UDP 51820，并能访问中心 HTTPS。
2. 可以用仓库里的 `deploy/ubuntu/gateway-ssh.sh`，将它以 0750 安装到 `/etc/regional-vpn/gateway-ssh`，设为 `root:regionalvpn`。脚本使用 `ubuntu` 账户。将核验过的节点主机公钥登记到 `/etc/regional-vpn/gateway-known-hosts`，让服务用户可读。使用密钥登录时，将 `/etc/regional-vpn/gateway-ssh-key` 设为服务用户所有、权限 0400。自定义授权脚本也可以由你单独维护。
3. 以 root 在中心创建权限为 0600 的 `/etc/regional-vpn/gateway-bootstrap.env`，填入以下配置。用 `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'` 生成接入密钥，保存到该文件。保留这把接入密钥以便中途失败后复用原登记。

   ```dotenv
   VPN_GATEWAY_SSH_HELPER=/etc/regional-vpn/gateway-ssh
   VPN_GATEWAY_CONTROL_URL=https://中心公网地址
   VPN_GATEWAY_BOOTSTRAP_KEY=填入上面生成的接入密钥
   ```

   如果节点已经允许 `ubuntu` 通过 SSH 密码登录，可在同一文件追加 `VPN_GATEWAY_SSH_PASSWORD='节点登录密码'`。有值时脚本使用密码，删除该行后恢复密钥登录。前台启动中心时可在启动命令所在的 shell 导出这个变量。systemd 启动的中心从该文件读取，修改后重启 `regional-control`。

4. 安装新版中心服务单元，执行 `sudo systemctl daemon-reload` 和 `sudo systemctl restart regional-control`。自动接入失败时，在处理提示中的问题后用同一 IP 和地域重试。

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

1. 打开已部署的 HTTPS 中心后台，选择「节点 → 接入新 Ubuntu 节点」。在云控制台复制新机器的公网 IPv4，并开放入站 UDP 51820。SSH 使用新机器的 `ubuntu` 登录凭据。
2. 下载部署包并填写公网 IPv4。在 Mac 终端运行页面生成的 `scp` 和 `ssh` 命令。登录新机器后，运行页面给出的解压和安装命令。WireGuard 公钥出现在 `Gateway public key:` 后面，随时可用 `sudo wg show wg-regional public-key` 重查。私钥保存在新机器。
3. 把公钥和地域填入后台并登记。下载 `gateway-节点名.json`，按页面命令从 Mac 上传，然后在 SSH 终端运行 `scripts/install-wireguard-agent.sh`。脚本先验证中心 HTTPS，再安装凭证（0600）并启动 Agent。Ubuntu 中心提供的部署包附带公开证书。
4. 回到后台点「检查 Agent 心跳」。出现「待核验」后，检查云安全组、出口公网 IPv4，再点「上线」。最后用客户端连接对应地域，验证实际出口。更换旧机时，先确保新机能接单，再对旧机执行「排空」和「退役」。

同机网关仍使用 `deploy/ubuntu/regional-gateway.service`。后台部署包面向独立 Ubuntu 节点。
本地 `localhost` 后台可预览流程，实际接入时需用线上 HTTPS 中心。

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
