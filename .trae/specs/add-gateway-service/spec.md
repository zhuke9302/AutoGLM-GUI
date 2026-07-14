# 公网网关服务 Spec

## Why
客户端（AutoGLM-GUI）部署在各巡检现场的内网，服务端（falconconsole）部署在管理中心内网，两者无法直接通信。需要新增一个部署在公网的网关服务，作为客户端与服务端之间的数据中转站，使所有数据推拉都经过网关，解决跨网络通信问题。

**关键约束**：网关部署在公网，**不能主动访问内网**，只能内网主动访问网关。因此服务端需要主动建立到网关的持久连接（隧道），网关通过该隧道转发客户端请求。

## What Changes
- 新增网关服务（Java/Spring Boot），部署在公网，作为客户端与服务端之间的数据中转站
- 网关暴露客户端 API 端点（与当前服务端客户端 API 路径一致），客户端无需修改 API 调用代码
- 网关暴露隧道端点，服务端主动建立 WebSocket 长连接到网关
- 客户端 HTTP 请求到达网关后，网关通过 WebSocket 隧道转发给服务端，服务端处理后将响应通过隧道返回
- 网关管理客户端 SSE 连接，服务端通过隧道推送 SSE 事件，网关转发给对应客户端
- 网关实现客户端 JWT 本地验证（与服务端共享密钥），快速拒绝无效请求
- 网关实现速率限制、连接数限制、TLS 终止、健康检查
- 服务端新增 TunnelClient 组件，主动建立并维护到网关的 WebSocket 隧道
- 服务端新增 TunnelEventSender 组件，替代 SseEmitterManager 通过隧道推送事件
- 客户端配置变更：`server_url` 指向网关公网地址（仅配置变更，代码不变）

## Impact
- Affected specs: 客户端同步模块（服务端地址配置）、服务端 SSE 推送机制
- Affected code:
  - 新增 `cuc-ikb-ai-xunjian-repository/gateway/` 目录（Java/Spring Boot 项目）
  - `AutoGLM_GUI/sync/client.py` — 无代码变更，仅 `server_url` 配置指向网关
  - `falconconsole/.../tunnel/TunnelClient.java` — 新增 WebSocket 隧道客户端
  - `falconconsole/.../tunnel/TunnelConfig.java` — 新增隧道配置
  - `falconconsole/.../tunnel/TunnelMessage.java` — 新增隧道消息模型
  - `falconconsole/.../tunnel/TunnelEventSender.java` — 新增隧道事件发送器（替代 SseEmitterManager）
  - `falconconsole/.../service/SseEmitterManager.java` — 隧道模式下不再直接发送事件，由 TunnelEventSender 接管
  - `falconconsole/.../config/ClientProperties.java` — 新增 `gatewayTunnelUrl` 配置项
  - `falconconsole/.../application.yml` — 新增 `falcon.client.gateway-tunnel-url` 配置

## 架构图

```
┌──────────────┐   HTTPS / SSE    ┌──────────────┐   WebSocket 隧道   ┌──────────────┐
│    Client    │ ◄──────────────► │    Gateway    │ ◄────────────────► │    Server    │
│ (AutoGLM-    │   公网            │(Java/Spring  │   内网主动建立       │ (falconcon-  │
│  GUI)        │                  │   Boot)      │   出站连接           │  sole)       │
└──────────────┘                  │   公网部署     │                    └──────────────┘
                                  └──────────────┘                          │
                                         │                           TunnelClient
                                    TLS 终止                      TunnelEventSender
                                    JWT 验证
                                    速率限制
                                    SSE 管理
                                    隧道转发
```

**数据流**：

1. **服务端启动** → 主动建立 WebSocket 连接到网关 `wss://gateway.example.com/api/v1/tunnel`
2. **客户端 HTTP 请求** → 网关验证 JWT → 通过 WebSocket 隧道转发给服务端 → 服务端本地处理 → 通过隧道返回响应 → 网关返回给客户端
3. **服务端 SSE 推送** → 服务端通过隧道发送 SSE 事件 → 网关转发给对应客户端的 SSE 连接
4. **客户端 SSE 连接** → 网关管理 SSE 连接，通过隧道订阅/取消订阅事件

---

## 隧道协议

服务端与网关之间通过 WebSocket 交换 JSON 消息，消息格式如下：

### 网关 → 服务端消息

**http_request** — 转发客户端 HTTP 请求
```json
{
  "type": "http_request",
  "request_id": "uuid",
  "client_id": "uuid | null",
  "method": "POST",
  "path": "/v1/clients/register",
  "headers": {"Content-Type": "application/json", "Authorization": "Bearer ..."},
  "body": "<base64-encoded>"
}
```

**sse_subscribe** — 客户端建立 SSE 连接
```json
{
  "type": "sse_subscribe",
  "client_id": "uuid"
}
```

**sse_unsubscribe** — 客户端断开 SSE 连接
```json
{
  "type": "sse_unsubscribe",
  "client_id": "uuid"
}
```

**file_uploaded** — 客户端上传文件通知（网关暂存文件后通知服务端拉取）
```json
{
  "type": "file_uploaded",
  "file_id": "uuid",
  "client_id": "uuid",
  "task_run_id": "uuid",
  "category": "screenshot",
  "filename": "screenshot_001.png",
  "mime_type": "image/png",
  "size_bytes": 123456
}
```

**ping** — 保活
```json
{"type": "ping"}
```

### 服务端 → 网关消息

**http_response** — 响应转发的 HTTP 请求
```json
{
  "type": "http_response",
  "request_id": "uuid",
  "status": 200,
  "headers": {"Content-Type": "application/json"},
  "body": "<base64-encoded>"
}
```

**sse_event** — 推送 SSE 事件给指定客户端
```json
{
  "type": "sse_event",
  "client_id": "uuid",
  "event_name": "scheduled_task.changed",
  "data": "{\"action\":\"updated\",\"id\":\"...\"}"
}
```

**sse_broadcast** — 广播 SSE 事件给所有客户端
```json
{
  "type": "sse_broadcast",
  "event_name": "ping",
  "data": "{}"
}
```

**file_ack** — 服务端确认已拉取文件，网关可删除暂存文件
```json
{
  "type": "file_ack",
  "file_id": "uuid"
}
```

**pong** — 保活响应
```json
{"type": "pong"}
```

---

## 文件传输机制

由于网关不能主动访问内网，截图等大文件不能通过 WebSocket 隧道 base64 传输（效率低、内存压力大），采用**网关暂存 + 服务端拉取**模式：

```
Client ──HTTP POST──► Gateway ──file_uploaded──► Server
                         │                         │
                    暂存到本地磁盘              拉取文件
                         │                    (出站 HTTP GET)
                         │                         │
                         ◄─────── file_ack ─────────┘
                         │
                    删除暂存文件
```

**流程**：
1. 客户端 POST `/api/v1/clients/{client_id}/uploads` 上传文件到网关（multipart/form-data）
2. 网关验证 JWT，将文件暂存到本地磁盘，生成 file_id
3. 网关立即返回响应给客户端：`{"url": "https://gateway.example.com/api/v1/files/{file_id}", "file_id": "uuid"}`
4. 网关通过隧道发送 `file_uploaded` 通知给服务端
5. 服务端收到通知后，通过出站 HTTP GET 从网关拉取文件：`GET https://gateway.example.com/api/v1/files/{file_id}`
6. 服务端存储文件到永久位置，创建 `patrol_client_uploaded_files` 记录
7. 服务端通过隧道发送 `file_ack` 给网关
8. 网关收到 `file_ack` 后删除暂存文件

**文件清理**：网关对超过 24 小时未被 ack 的暂存文件自动清理

**网关文件端点**：
- `GET /api/v1/files/{file_id}` — 服务端拉取暂存文件（需 `X-Tunnel-Key` 认证）

---

## ADDED Requirements

### Requirement: 网关隧道端点
网关 SHALL 提供 WebSocket 隧道端点，供服务端主动连接。

#### Scenario: 服务端建立隧道连接
- **WHEN** 服务端 WebSocket 连接到 `/api/v1/tunnel`，携带有效的 `X-Tunnel-Key` 认证头
- **THEN** 网关验证 Tunnel Key，建立隧道连接，开始转发客户端请求

#### Scenario: 隧道认证失败
- **WHEN** WebSocket 连接携带无效的 `X-Tunnel-Key`
- **THEN** 网关关闭 WebSocket 连接，返回 401

#### Scenario: 隧道断开重连
- **WHEN** WebSocket 连接断开
- **THEN** 网关清理隧道状态，暂停接受客户端请求（返回 502），等待服务端重新连接

#### Scenario: 隧道保活
- **THEN** 网关每 30 秒发送 `ping` 消息，服务端应回复 `pong`；超时未回复则断开隧道

### Requirement: 网关客户端 HTTP 代理
网关 SHALL 接受客户端 HTTP 请求，通过隧道转发给服务端，返回服务端响应。

#### Scenario: 代理客户端注册请求
- **WHEN** 客户端 POST `/api/v1/clients/register` 到网关
- **THEN** 网关通过隧道转发请求给服务端，服务端处理后将响应通过隧道返回，网关返回给客户端

#### Scenario: 代理需认证的客户端请求
- **WHEN** 客户端发送需认证的请求（心跳、设备上报、任务同步、工作流同步、配置同步、日志上报、任务控制等）
- **THEN** 网关验证 JWT 通过后，通过隧道转发给服务端，返回服务端响应

#### Scenario: 代理文件上传请求
- **WHEN** 客户端 POST `/api/v1/clients/{client_id}/uploads`（multipart/form-data）到网关
- **THEN** 网关验证 JWT 后，将文件暂存到本地磁盘，立即返回 `{"url": "...", "file_id": "..."}` 给客户端，通过隧道发送 `file_uploaded` 通知服务端拉取

#### Scenario: 隧道未建立
- **WHEN** 客户端请求到达网关但隧道未建立（服务端未连接）
- **THEN** 返回 502 Bad Gateway 给客户端

#### Scenario: 隧道转发超时
- **WHEN** 隧道转发请求后服务端未在 30s 内响应
- **THEN** 返回 504 Gateway Timeout 给客户端

### Requirement: 网关 SSE 管理
网关 SHALL 管理客户端 SSE 连接，通过隧道接收服务端推送的事件并转发给客户端。

#### Scenario: 客户端建立 SSE 连接
- **WHEN** 客户端 GET `/api/v1/clients/{client_id}/events/stream` 到网关
- **THEN** 网关验证 JWT，建立 SSE 连接，通过隧道发送 `sse_subscribe` 消息给服务端，立即发送 `connected` 事件给客户端

#### Scenario: SSE 事件转发
- **WHEN** 服务端通过隧道发送 `sse_event` 消息
- **THEN** 网关将事件转发给对应 client_id 的 SSE 连接，中继延迟 < 100ms

#### Scenario: SSE 广播转发
- **WHEN** 服务端通过隧道发送 `sse_broadcast` 消息
- **THEN** 网关将事件转发给所有已连接的客户端 SSE 连接

#### Scenario: 客户端 SSE 断开
- **WHEN** 客户端断开 SSE 连接
- **THEN** 网关通过隧道发送 `sse_unsubscribe` 消息给服务端，释放 SSE 资源

#### Scenario: 隧道断开时 SSE 处理
- **WHEN** 隧道断开
- **THEN** 网关保持客户端 SSE 连接，定期发送 `ping` 保活；隧道重连后重新发送 `sse_subscribe`

#### Scenario: SSE 连接数限制
- **THEN** 每个客户端 ID 最多 1 个 SSE 连接，新连接建立时关闭旧连接

### Requirement: 网关文件暂存
网关 SHALL 暂存客户端上传的文件，供服务端后续拉取。

#### Scenario: 客户端上传文件
- **WHEN** 客户端 POST `/api/v1/clients/{client_id}/uploads`（multipart/form-data）
- **THEN** 网关将文件保存到本地磁盘（配置的 `storage.dir` 目录），生成 file_id，立即返回 `{"url": "https://{gateway_host}/api/v1/files/{file_id}", "file_id": "uuid"}` 给客户端

#### Scenario: 通知服务端拉取
- **THEN** 文件暂存后，网关通过隧道发送 `file_uploaded` 消息给服务端，包含 file_id、client_id、task_run_id、category、filename、mime_type、size_bytes

#### Scenario: 服务端拉取文件
- **WHEN** 服务端 GET `/api/v1/files/{file_id}`，携带 `X-Tunnel-Key` 认证
- **THEN** 网关返回暂存文件内容（Content-Type 为文件原始 MIME 类型）

#### Scenario: 服务端确认拉取
- **WHEN** 服务端通过隧道发送 `file_ack` 消息
- **THEN** 网关删除对应的暂存文件

#### Scenario: 文件自动清理
- **WHEN** 暂存文件超过 24 小时未被 ack
- **THEN** 网关自动删除该文件

#### Scenario: 文件不存在
- **WHEN** 服务端请求的 file_id 不存在（已被清理或未上传）
- **THEN** 返回 404 Not Found

### Requirement: 网关客户端 JWT 验证
网关 SHALL 在本地验证客户端 JWT，快速拒绝无效请求。

#### Scenario: 有效 JWT
- **WHEN** 客户端请求携带有效 JWT
- **THEN** 网关验证通过，通过隧道转发请求

#### Scenario: 无效或过期 JWT
- **WHEN** 客户端请求携带无效或过期 JWT
- **THEN** 网关直接返回 401 Unauthorized，不通过隧道转发

#### Scenario: 注册接口免验证
- **WHEN** 客户端请求 `/api/v1/clients/register`
- **THEN** 网关不验证 JWT，直接通过隧道转发

#### Scenario: JWT 密钥共享
- **THEN** 网关与服务端使用相同的 JWT 密钥（`falcon.client.jwt-secret`），网关可本地验证 JWT 签名和有效期

### Requirement: 网关速率限制
网关 SHALL 实现速率限制，防止客户端滥用。

#### Scenario: 全局速率限制
- **THEN** 每个客户端 IP 每秒最多 30 个请求

#### Scenario: 超出速率限制
- **WHEN** 请求超出速率限制
- **THEN** 返回 429 Too Many Requests

### Requirement: 网关 TLS 终止
网关 SHALL 提供 HTTPS 服务，终止 TLS 连接。

#### Scenario: HTTPS 监听
- **THEN** 网关监听 443 端口（HTTPS），同时监听 80 端口并重定向到 HTTPS

#### Scenario: 证书配置
- **THEN** TLS 证书路径通过配置文件指定，支持 PKCS12 和 PEM 格式

#### Scenario: 无证书时 HTTP 模式
- **WHEN** 未配置 TLS 证书
- **THEN** 网关仅监听 HTTP 端口（适用于前置 Nginx/CDN 终止 TLS 的场景）

### Requirement: 网关健康检查
网关 SHALL 提供健康检查端点。

#### Scenario: 健康检查
- **WHEN** GET `/health`
- **THEN** 返回 `{"status": "ok", "tunnel_connected": true/false}`，`tunnel_connected` 表示服务端隧道是否已建立

### Requirement: 网关配置
网关 SHALL 通过 application.yml 配置文件和环境变量进行配置，环境变量优先级高于配置文件。

#### Scenario: 配置项
- **THEN** 支持以下配置项：
  - `gateway.tunnel.key` — 隧道认证密钥，服务端连接时需提供（必填）
  - `gateway.tunnel.ping-interval` — 隧道保活间隔（默认 30s）
  - `gateway.tunnel.request-timeout` — 隧道请求超时（默认 30s）
  - `gateway.jwt.secret` — JWT 密钥，与服务端共享（必填）
  - `gateway.tls.enabled` — 是否启用 TLS（默认 false）
  - `gateway.tls.cert` — TLS 证书路径（可选，PKCS12 或 PEM）
  - `gateway.tls.key` — TLS 私钥路径（可选）
  - `gateway.tls.key-store` — TLS PKCS12 keystore 路径（可选）
  - `gateway.tls.key-store-password` — TLS keystore 密码（可选）
  - `server.port` — HTTP 监听端口（默认 8080）
  - `gateway.https.port` — HTTPS 监听端口（默认 8443，启用 TLS 时生效）
  - `gateway.ratelimit.rps` — 每秒请求限制（默认 30）
  - `gateway.storage.dir` — 文件暂存目录（默认 `./uploads`）
  - `gateway.storage.cleanup-hours` — 暂存文件自动清理时间（默认 24 小时）
  - `gateway.storage.base-url` — 文件访问基础 URL（如 `https://gateway.example.com`，必填）
  - `logging.level.root` — 日志级别（默认 `INFO`）

#### Scenario: 环境变量覆盖
- **THEN** Spring Boot 标准环境变量格式，如 `GATEWAY_TUNNEL_KEY`、`GATEWAY_JWT_SECRET` 等

### Requirement: 网关 Docker 部署
网关 SHALL 支持 Docker 部署。

#### Scenario: Docker 构建
- **THEN** 提供 Dockerfile，基于 Eclipse Temurin JDK 17 构建

#### Scenario: Docker Compose 部署
- **THEN** 提供 docker-compose.yml，通过环境变量配置

### Requirement: 网关项目结构
网关 SHALL 为独立 Spring Boot 项目，遵循 Maven 标准布局。

#### Scenario: 目录结构
- **THEN** 项目结构如下：
  ```
  gateway/
  ├── pom.xml                                    # Maven 项目描述
  ├── src/
  │   ├── main/
  │   │   ├── java/com/falcon/gateway/
  │   │   │   ├── GatewayApplication.java        # Spring Boot 入口
  │   │   │   ├── config/
  │   │   │   │   ├── GatewayProperties.java     # 配置属性（@ConfigurationProperties）
  │   │   │   │   ├── WebSocketConfig.java       # WebSocket 配置
  │   │   │   │   └── WebConfig.java             # Web MVC 配置（拦截器注册）
  │   │   │   ├── middleware/
  │   │   │   │   ├── ClientAuthInterceptor.java # JWT 验证拦截器
  │   │   │   │   └── RateLimitInterceptor.java  # 速率限制拦截器
  │   │   │   ├── proxy/
  │   │   │   │   └── ClientProxyController.java # 客户端 HTTP 请求代理（通过隧道转发）
  │   │   │   ├── storage/
  │   │   │   │   ├── FileStorageController.java # 文件上传/下载端点
  │   │   │   │   └── FileStorageService.java    # 文件暂存管理（保存、读取、清理）
  │   │   │   ├── sse/
  │   │   │   │   ├── SseController.java         # 客户端 SSE 连接端点
  │   │   │   │   └── SseManager.java            # SSE 连接管理与事件转发
  │   │   │   ├── tunnel/
  │   │   │   │   ├── TunnelHandler.java         # WebSocket 隧道端点处理
  │   │   │   │   ├── TunnelManager.java         # 隧道连接管理（请求路由、响应分发）
  │   │   │   │   └── TunnelMessage.java         # 隧道消息协议定义
  │   │   │   └── health/
  │   │   │       └── HealthController.java      # 健康检查
  │   │   └── resources/
  │   │       └── application.yml                # 默认配置
  │   └── test/
  │       └── java/com/falcon/gateway/
  │           └── ...                            # 单元测试
  ├── Dockerfile
  ├── docker-compose.yml
  └── application-example.yml                    # 示例配置
  ```

#### Scenario: 技术栈
- **THEN** 网关使用以下技术栈：
  - Java 17 + Spring Boot 3.2.x（与 falconconsole 保持一致）
  - spring-boot-starter-web（HTTP 服务）
  - spring-boot-starter-websocket（WebSocket 隧道端点）
  - jjwt 0.12.x（JWT 验证，与 falconconsole 使用相同库）
  - Lombok（减少样板代码）
  - Maven 构建

### Requirement: 服务端 TunnelClient
服务端 SHALL 新增 TunnelClient 组件，主动建立并维护到网关的 WebSocket 隧道。

#### Scenario: 启动时建立隧道
- **WHEN** 服务端启动且配置了 `falcon.client.gateway-tunnel-url`
- **THEN** TunnelClient 主动建立 WebSocket 连接到网关隧道端点，携带 `X-Tunnel-Key` 认证

#### Scenario: 隧道断开自动重连
- **WHEN** WebSocket 连接断开
- **THEN** TunnelClient 自动重连（指数退避 1s→2s→4s→...→30s），重连成功后恢复请求处理

#### Scenario: 接收并处理隧道请求
- **WHEN** TunnelClient 收到 `http_request` 消息
- **THEN** 将请求转发到本地服务端 API（`http://localhost:8080/api/...`），处理后将响应通过隧道返回

#### Scenario: 接收文件上传通知
- **WHEN** TunnelClient 收到 `file_uploaded` 消息
- **THEN** 通过出站 HTTP GET 从网关拉取暂存文件（`GET https://{gateway_host}/api/v1/files/{file_id}`，携带 `X-Tunnel-Key`），存储到服务端永久位置，创建 `patrol_client_uploaded_files` 记录，通过隧道发送 `file_ack` 确认

#### Scenario: 隧道保活
- **WHEN** TunnelClient 收到 `ping` 消息
- **THEN** 回复 `pong` 消息

#### Scenario: 未配置隧道 URL
- **WHEN** 未配置 `falcon.client.gateway-tunnel-url`
- **THEN** TunnelClient 不启动，服务端保持原有直连模式（向后兼容）

### Requirement: 服务端 TunnelEventSender
服务端 SHALL 新增 TunnelEventSender 组件，通过隧道推送 SSE 事件给客户端。

#### Scenario: 通过隧道推送事件
- **WHEN** 服务端需要向客户端推送 SSE 事件（定时任务变更、工作流变更、配置变更、任务取消、任务调度等）
- **THEN** TunnelEventSender 通过隧道发送 `sse_event` 或 `sse_broadcast` 消息给网关

#### Scenario: 替代 SseEmitterManager
- **WHEN** 隧道模式启用（配置了 `gateway-tunnel-url`）
- **THEN** SSE 事件通过 TunnelEventSender 发送（经隧道到网关再到客户端），SseEmitterManager 不再直接发送事件

#### Scenario: 隧道模式未启用
- **WHEN** 未配置 `gateway-tunnel-url`
- **THEN** 继续使用 SseEmitterManager 直接发送事件（向后兼容直连模式）

---

## MODIFIED Requirements

### Requirement: 客户端服务端地址配置
客户端同步模块的 `server_url` SHALL 指向网关公网地址，而非服务端内网地址。

#### Scenario: 配置网关地址
- **WHEN** 配置了 `server_url` 为网关公网地址（如 `https://gateway.example.com/api`）
- **THEN** 客户端所有同步请求发送到网关，SSE 连接建立到网关，API 路径不变

### Requirement: 服务端 SSE 推送机制
服务端 SSE 推送 SHALL 支持两种模式：直连模式（SseEmitterManager）和隧道模式（TunnelEventSender）。

#### Scenario: 隧道模式
- **WHEN** 配置了 `falcon.client.gateway-tunnel-url`
- **THEN** SSE 事件通过 TunnelEventSender → 隧道 → 网关 → 客户端 SSE 连接推送

#### Scenario: 直连模式
- **WHEN** 未配置 `falcon.client.gateway-tunnel-url`
- **THEN** SSE 事件通过 SseEmitterManager 直接推送给客户端（当前行为不变）
