# Regional VPN 项目交接

更新于 2026-11-13，北京时间。实现基线为 `e603173`，开发和交接分支为 `regional-vpn-pilot`。

## 仓库与项目目标

```bash
git clone --branch regional-vpn-pilot git@github.com:cyrishe/vpn_tool.git
cd vpn_tool
```

GitHub 默认分支 `master` 仍是早期版本。继续开发请从 `regional-vpn-pilot` 开始。本机当前代码仓库是 `/Users/chenghe/work/vpn_tool-dev`。`/Users/chenghe/work/vpn_tools` 是早期工作目录，含非项目资料。交接所需的服务端、网关、客户端、安装脚本和配置模板已纳入当前仓库。

首版面向个人，规划订阅价 ¥10–20/月，先人工开通，使用共享出口。用户登录后只看已开通的地域。中心负责账号、权限、节点登记和调度，客户端直接连接所选地域的 WireGuard 网关。地域和机器独立，换机器时在原地域登记新节点，客户端无需发版。产品验收指标是实际公网出口和目标平台显示的省份，设备定位仍由操作系统和应用处理。

## 交付与验证状态

| 模块 | 当前状态 | 验证边界 |
| --- | --- | --- |
| Ubuntu 中心与上海出口 | 已知部署为 `101.34.21.167`，中心与唯一上海网关同机运行。Ubuntu + SQLite + systemd，中心走 HTTPS 443，WireGuard 走 UDP 51820 | 11 月 13 日重新检查，`/healthz` 返回 `ok`，线上 `/admin` 返回 404。此前已验证真实 Peer 下发、撤销、重启和备份恢复校验。本次只复查 HTTP，未重跑隧道验收 |
| 服务端主干 | 用户登录、按地域授权、设备注册、节点心跳、容量调度、两阶段切换、短租约与到期撤权已实现 | 服务端 20 项测试通过。同地域多节点调度有集成测试，跨省真实节点待验收 |
| 管理后台 | 地域新增、改名、启停；节点登记、心跳、上线、排空、退役；账号人工开通与修改有效期 | 本地 `http://127.0.0.1:8018/admin` 返回 200，此前已验证浏览器操作。线上入口待部署启用 |
| 节点接入 | 手动流程可下载部署包与凭证。自动流程填公网 IPv4 和地域，由中心 SSH 安装 WireGuard、取公钥、登记并启动 Agent。支持同 IP、同地域重试 | 模拟 SSH 的页面及后端流程通过。真实 OpenSSH 已在本机测试服务验证密码、密钥、错误密码、未知主机和二进制 stdin 传输。尚未在一台新的 Ubuntu 上端到端跑通 |
| macOS 联调客户端 | AppKit 版和 CLI 走真实 WireGuard，依赖本机 `wg-quick` 等工具，连接和断开可能提示管理员授权 | 已有真实出口联调记录。本次未重测公网出口、IPv6 和 DNS |
| macOS 发布版 | macOS 14+，内置 WireGuard 系统扩展。首次批准系统 VPN 配置，之后设计为复用批准。可走 Developer ID 签名和 Apple 公证后直发 | 工程可生成，客户端 Swift 类型检查和线上登录、恢复会话、读取上海地域已验证。完整 Xcode 构建、签名、公证及免反复输密码的真机体验待验收。[构建与验收](macos-native-vpn.md) · [Apple 分发说明](https://developer.apple.com/documentation/technotes/tn3134-network-extension-provider-deployment) |
| 后续产品能力 | 移动端、支付自动化、云资源采购自动化、节点故障自动迁移待做 | 先验证第二个真实地域和 macOS 发布包，再排期 |

代码提交依次包含 Ubuntu 联调 `b3fad7b`、macOS 系统 VPN `fc70717`、管理后台 `b0702f1`、手动接入 `758cd09`、自动接入 `2c1af4e` 和可选 SSH 密码 `e603173`。

## 接手后先做什么

1. **启用线上后台。** 在维护窗口部署试运行分支的中心代码与 systemd 单元，按部署文档配置管理员密钥。验证 `/healthz`、后台登录和上海节点状态。SQLite 数据库位于 `/var/lib/regional-vpn/control.db`，备份和恢复步骤见部署文档。[Ubuntu 部署与运维](ubuntu-deployment.md)
2. **接一台外地 Ubuntu。** 优先用贵阳或太原验证整条链路。机器需支持独立公网 IPv4、入站 UDP 51820、中心发起 SSH、节点出站 HTTPS。自动接入还需要 `ubuntu` 可执行 `sudo -n`，中心使用已核验的 SSH 主机公钥和密钥或可选密码。后台录入 IP 与地域，收到心跳后核验并上线。用客户端验证实际出口、断开恢复，以及排空和退役行为。[自动接入配置](ubuntu-deployment.md#启用自动接入)
3. **在具备签名条件的 Mac 上完成打包。** 安装完整 Xcode 和构建依赖，配置 Apple Developer Team、App 与系统扩展的签名和权限。用干净 Mac 验证首次系统审批、重开 App、三次连接与断开、两地域切换、失败回滚、DNS 和 IPv6 路由。[macOS 发布版验收](macos-native-vpn.md#签名包验收)
4. **逐省扩展供给。** 先拿到测试 IP 和可开通报价，记录可用的省份和供应商。保留上海联调节点，优先做贵州、山西、内蒙古，随后验证新疆和云南，西藏单独询价。正式付费开放前，根据实际服务范围确认云商合同和经营许可要求。[主管部门业务准入说明](https://gdca.miit.gov.cn/bsfw/bszn/jyxk/art/2020/art_663d22b0dc8f4d1d9465579f38d22d1a.html)

本地可在 `service/` 安装 `requirements.txt` 后运行 `python3 -m pytest -q`。演示后台使用独立本地 SQLite 和管理员访问密钥。生产管理员密钥、SSH 密码和私钥、节点凭证、真实账号、数据库与备份从对应环境的授权渠道交接。运行态文件在 Git 忽略范围内，构建 Mac 客户端需要从中心取得公开证书。

## 省级节点调研

以下是公开资料确认的采购入口及线索。截至交接日，尚未用采购账号核实库存，也未购买或验证这六省的出口 IP。天翼云的资源池名称需在 **ECS 可售规格**里复核，部分旧池的停售说明属于具体产品。此前对「昆明2」「拉萨3」的停售判断应以此为准，MySQL 等产品的停售公告无法确认 ECS 库存。[天翼云 ECS 规格与可售地域入口](https://www.ctyun.cn/document/10026730/10138523) · [MySQL 产品公告](https://www.ctyun.cn/document/10034282/11057090)

| 地域 | 优先查的供应商与节点 | 当前证据和待确认项 |
| --- | --- | --- |
| 贵州 | 华为云 ECS「西南-贵阳一」，备选天翼云「西南2-贵州」 | 华为云 Linux ECS 官方购买示例明确使用贵阳一，可优先看小规格和公网 IP。天翼云也公开列出对应资源池。[华为云购买说明](https://support.huaweicloud.com/qs-ecs/ecs_01_0103.html) · [天翼云资源池](https://www.ctyun.cn/document/10033813/11095008) |
| 山西 | 天翼云「太原4」 | 天翼云公开列出资源池，云专线接入点资料也给出太原机房位置。需要在 ECS 控制台核实 Ubuntu、库存和公网 IP。[资源池](https://www.ctyun.cn/document/10033813/11095008) · [机房位置](https://www.ctyun.cn/qzdh/143805_185) |
| 内蒙古 | 阿里云 ECS「呼和浩特」「乌兰察布」，备选天翼云「呼和浩特3」 | 阿里云明确列为 ECS 地域。天翼云也有资源池候选，适合对比两家公网 IP 和报价。[阿里云 ECS 地域](https://help.aliyun.com/zh/egs/regions-and-zones-1) · [天翼云资源池](https://www.ctyun.cn/document/10033813/11095008) |
| 新疆 | 天翼云「乌鲁木齐7」 | 天翼云列出该资源池，云专线资料将该接入点定位在新疆昌吉。阿里云常规 ECS 官方明确无新疆地域。核实天翼云 ECS 实际可售及出口 IP。[天翼云资源池](https://www.ctyun.cn/document/10033813/11095008) · [接入点位置](https://www.ctyun.cn/qzdh/143805_185) · [阿里云 ECS 地域](https://help.aliyun.com/zh/egs/regions-and-zones-1) |
| 云南 | 云南电信、移动云昆明，备选特普数据昆明云主机 | 中国电信确认云南省内云资源布局。特普数据公开列出昆明 Linux 云主机、一个 IP，标价 ¥60/月起。IPv4 类型、Ubuntu、UDP、库存和最终成交价待确认。天翼云「昆明2」有资源池记录，单独核实是否接受 ECS 新购。[云南电信](https://www.chinatelecom.com.cn/ct/news/gdxw/162446.html) · [昆明云主机选购页](https://www.tpidc.com/shop/1/26.html) · [天翼云资源池](https://www.ctyun.cn/document/10026755/10196575) |
| 西藏 | 中国移动西藏拉萨数据中心，备选拉萨本地 IDC 与天翼云 ECX | 拉萨市政府确认移动拉萨数据中心提供云服务器和托管。西藏新拓电讯公开列有拉萨云主机服务。个人账号能否开通小规格、公网 IPv4 和 UDP 需询价核实。天翼云「拉萨3」有资源池记录，ECS 新购待核实。[拉萨市政府](https://www.lasa.gov.cn/lasa/lsyw/202502/1796925081474dc68eb60ea1a091035a.shtml) · [西藏本地 IDC](https://xzidc.com/) · [天翼云资源池](https://www.ctyun.cn/document/10026755/10196575) |

覆盖更多省份时，可用**常规云主机 + 边缘虚拟机 + 本地运营商或 IDC**三条采购路径。阿里云 ENS 可按节点能力查计算实例与网络，需企业认证，部分节点需白名单。腾讯云 ECM 提供节点查询与购买入口，火山引擎可按实例规格查询可开通的城市和运营商。天翼云 ECX 文档称覆盖 31 省，资源池需联系客户经理确认。覆盖说明仅用于找候选，采购以指定节点、规格、账号和 EIP 可用性为准。[阿里云 ENS 能力地图](https://help.aliyun.com/zh/ens/getting-started/product-capability-map) · [ENS 开通](https://help.aliyun.com/zh/ens/getting-started/overview-3) · [腾讯云 ECM 节点查询](https://cloud.tencent.com/document/product/1108/42567) · [火山引擎可开通查询](https://docs.volcengine.com/docs/EdgeComputingNode/Obtainsupportedregionsandoperatorsforinstancespecifications?lang=zh) · [天翼云 ECX 节点分布](https://www.ctyun.cn/document/10011497/10136582)

询价时要求供应商明确机房城市、运营商、独立公网 IPv4、Ubuntu、入站 UDP 51820、最短试用或按量周期，以及云主机与公网 IP 的合计价格。请供应商提供同资源池的测试 IP。实际开通后，记录客户端所见出口 IPv4、至少两家查询服务的省份结果，以及目标平台测试账号的显示结果。不同 IP 定位数据库的结果可能不同。竞价实例有回收风险，先用按量或短周期机器完成基线验收。[百度 IP 定位](https://lbsyun.baidu.com/docs/webapi?title=locationip%2Fip-api-base) · [MaxMind 定位精度说明](https://support.maxmind.com/knowledge-base/articles/maxmind-geolocation-accuracy) · [腾讯云竞价实例说明](https://cloud.tencent.com/document/product/213/17817)
