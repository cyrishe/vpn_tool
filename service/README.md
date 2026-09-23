# Control Plane Service

Regional VPN 的中心控制面。当前提供开发态账户、订阅地区、设备注册和两阶段
地区切换 API。数据面为模拟网关，不会创建或修改真实 VPN。

## 启动

```bash
uvicorn control_plane.app:app --reload
```

默认监听 `127.0.0.1:8000`，OpenAPI 页面为：

```text
http://127.0.0.1:8000/docs
```

开发演示账户：

```text
demo@example.com
demo-password
```

可通过环境变量修改：

```text
VPN_DATABASE_URL
VPN_ENVIRONMENT
VPN_DEMO_EMAIL
VPN_DEMO_PASSWORD
VPN_TOKEN_TTL_HOURS
```

## 测试

```bash
pytest -q
```

## 生产前必须替换

- SQLite 和自动建表
- 演示账号
- 单实例令牌管理
- 模拟 Gateway readiness
- 明文 HTTP
- 缺少限流、审计、监控和密钥管理
