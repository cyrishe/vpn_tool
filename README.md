# Regional VPN

## 固定服务器

当前联调中心部署在 Ubuntu `101.34.21.167`，数据库为服务器上的 SQLite，
服务、网关和备份均由 systemd 托管。客户端直接连接 HTTPS，不依赖 Mac 中心。
当前操作说明以 [Ubuntu 部署文档](docs/ubuntu-deployment.md) 为准。

最小原生 App：`bash scripts/build-macos-pilot.sh 101.34.21.167`。
节点在中心按地域动态登记和上下线，客户端不维护节点清单。

## 当前开发入口

以下为保留的本地开发预览，与正式 Ubuntu 中心独立。

核心服务端与地域节点接入见 [核心服务端](docs/core-server.md)。
正式客户端需要系统 VPN 隧道；下方网页仅为既有流程预览。

分模块计划和验收标准见 [开发计划](docs/development-plan.md)。
第一阶段提供浏览器可操作预览，连接仍为模拟，不改变 IP 或路由。

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r service/requirements.txt
cd service
python3 -m uvicorn control_plane.app:app --host 127.0.0.1 --port 8017
```

打开 <http://127.0.0.1:8017>，使用 `demo@example.com` / `demo-password`。
可验证登录、服务端地域列表、模拟连接、切换、断开和退出。
预览仅在 development 环境提供。浏览器不是系统 VPN 客户端。

本目录现在包含两个相互独立的部分：

1. 原有的 Tailscale Exit Node 个人测试脚本。
2. 正在开发的 Regional VPN 产品原型，包括中心控制面和 macOS 客户端。

浏览器预览和 Swift Package 示例使用模拟隧道。真实 WireGuard 出口已有
[命令行和 macOS 试运行客户端](docs/live-poc.md)。
[macOS 系统 VPN 客户端](docs/macos-native-vpn.md)内置 WireGuard，已实现复用系统授权的流程，签名安装和真机验收待完成。
架构和分阶段计划见 [docs/mvp-architecture.md](docs/mvp-architecture.md)。

## 产品原型快速启动

启动控制面：

```bash
cd service
uvicorn control_plane.app:app --reload
```

开发环境会创建 SQLite 数据库，并生成以下演示账户：

```text
邮箱：demo@example.com
密码：demo-password
```

启动 macOS 客户端：

```bash
cd macos/RegionalVPNClient
swift run RegionalVPNClient
```

运行测试：

```bash
cd service
pytest -q

cd ../macos/RegionalVPNClient
swift test
```

> 演示账号和 SQLite 自动建表只能用于本地开发，不可用于公网部署。

## 原有 Tailscale 测试

这个目录不实现新的 VPN 协议。它使用 Tailscale 自带的 VPN 客户端和
Exit Node 功能，只把 Linux 云服务器所需的转发配置封装成可重复执行的脚本。

当前可以先用已有的华南服务器验证链路。连接成功后，客户端公网 IP 应从
上海本地 IP 变成华南服务器的公网 IP。以后换成上海服务器，步骤完全相同。

## 1. 上传并运行服务器脚本

以下命令在本地电脑执行。把示例中的登录名和服务器地址换成真实值：

```bash
scp scripts/setup-tailscale-exit-node.sh user@server:/tmp/
ssh -t user@server 'bash /tmp/setup-tailscale-exit-node.sh'
```

脚本适用于常见的 Ubuntu、Debian 等 Linux 云服务器，并会：

1. 安装官方 Tailscale 客户端。
2. 开启 IPv4 和 IPv6 转发。
3. 设置 `tailscaled` 开机启动。
4. 登录 Tailscale。
5. 将服务器声明为 Exit Node。

第一次运行时终端会显示 Tailscale 登录链接。在浏览器打开链接并使用自己的
Tailscale Personal 账号登录。

如果想先查看脚本准备执行的操作，不修改服务器：

```bash
ssh -t user@server 'bash /tmp/setup-tailscale-exit-node.sh --dry-run'
```

## 2. 在 Tailscale 后台批准出口节点

打开：

<https://console.tailscale.com/admin/machines>

找到服务器，然后依次选择：

```text
Edit route settings
└── Use as exit node
```

完成后，服务器应显示 `Exit Node` 标记。建议把服务器命名为容易识别的名称，
例如 `guangdong-test-exit`，以后上海节点可命名为 `shanghai-exit`。

## 3. 检查服务器

把检查脚本上传到服务器并运行：

```bash
scp scripts/check-tailscale-exit-node.sh user@server:/tmp/
ssh user@server 'bash /tmp/check-tailscale-exit-node.sh'
```

IPv4 forwarding、IPv6 forwarding 和 tailscaled service 都应显示 `[OK]`。

## 4. 发笔记的电脑如何连接

客户端不需要运行本仓库脚本，也不需要安装 OpenVPN、WireGuard 或浏览器插件。
安装 Tailscale 桌面客户端即可：

<https://tailscale.com/download>

操作步骤：

1. 使用与服务器相同的 Tailscale 账号登录。
2. 点击 Windows 任务栏或 macOS 菜单栏里的 Tailscale 图标。
3. 打开 `Exit Nodes`。
4. 选择 `guangdong-test-exit`。
5. 浏览器搜索“我的 IP”，确认公网 IP 和地区已经改变。
6. 完全退出并重新打开小红书或浏览器发布后台。
7. 发布或测试完成后，在 `Exit Nodes` 中选择 `None`。

Tailscale 是操作系统级 VPN。选择 Exit Node 后，浏览器和桌面应用会共同使用
该出口，不需要在浏览器中填写代理地址。

## 5. 测试验收

建议记录以下结果：

| 状态 | 预期公网位置 |
| --- | --- |
| 未连接 Tailscale Exit Node | 当前上海宽带 |
| 连接华南测试 Exit Node | 华南服务器 IP 所属地区 |
| 断开 Exit Node | 恢复上海宽带 |

需要同时检查 IPv4 和 IPv6。云服务商标注的机房地区不一定等于公网 IP 数据库
显示的地区，因此将来购买上海节点前，最好先取得测试 IP 或先按月购买。

## 常见问题

- 客户端找不到服务器：检查管理后台是否开启 `Use as exit node`。
- 能看到服务器但无法上网：重新运行服务器检查脚本，确认转发均为 `[OK]`。
- 速度较慢：可能是云服务器带宽较低，或者连接通过 Tailscale 中继而不是直连。
- VPN 冲突：连接前关闭 Clash、Surge、公司 VPN 等其他系统级 VPN。
- 云安全组：首次测试通常不需要新增入站规则；服务器需要能够主动访问互联网。
