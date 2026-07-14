# 客户端、网关、服务端调用链逻辑及本地调试环境启动指南

## 一、整体架构

```
┌──────────────┐   HTTPS / SSE    ┌──────────────┐   WebSocket 隧道   ┌──────────────┐
│    Client    │ ◄──────────────► │    Gateway    │ ◄────────────────► │    Server    │
│ (AutoGLM-    │   公网            │(Java/Spring  │   内网主动建立       │ (falconcon-  │
│  GUI)        │                  │   Boot)      │   出站连接           │  sole)       │
└──────────────┘                  │   公网部署     │                    └──────────────┘
```

**核心约束**：网关部署在公网，无法访问内网；服务端在内网，通过主动建立出站 WebSocket 连接到网关，形成反向隧道。

---

## 二、调用链逻辑

### 2.1 隧道建立与保活

**触发条件**：服务端配置了 `falcon.client.gateway-tunnel-url`

**流程**：

```
Server ──── WebSocket CONNECT ────► Gateway
         Header: X-Tunnel-Key

Server ──── ping ────────────────► Gateway
Gateway ──── pong ───────────────► Server
         (每 30s 一次)
```

1. 服务端 `TunnelClient`（[`TunnelClient.java`](file:///g:/workspace/cuc-ikb-ai-xunjian-repository/falconconsole/src/main/java/com/falcon/patrol/tunnel/TunnelClient.java)）启动时主动发起 WebSocket 连接到网关 `ws://{gateway_host}/api/v1/tunnel`
2. 请求头携带 `X-Tunnel-Key` 认证
3. 网关 `TunnelManager`（[`TunnelManager.java`](file:///g:/workspace/cuc-ikb-ai-xunjian-repository/gateway/src/main/java/com/falcon/gateway/tunnel/TunnelManager.java)）验证密钥通过后建立持久连接
4. 网关通过已建立的隧道连接每 30s 发送 `ping`，服务端回复 `pong` 保活（隧道建立后为双向通信，网关无需主动连服务端）
5. 断线自动重连，指数退避：1s → 2s → 4s → ... → 30s

**向后兼容**：未配置 `gateway-tunnel-url` 时，`TunnelClient` Bean 不会被创建，服务端保持原有直连模式。

### 2.2 客户端 HTTP 请求代理

**适用场景**：客户端注册、心跳上报、任务同步、设备上报等

**流程**：

```
Client ──── HTTPS POST ──────────► Gateway
                                   │ JWT 验证 (ClientAuthInterceptor)
                                   │ 序列化为 http_request 隧道消息
                                   ▼
         Gateway ──── WebSocket ──► Server (TunnelClient)
                                   │ 转发到本地 http://localhost:8080/api{path}
                                   │ 获取响应，序列化为 http_response
                                   ▼
Client ◄─── HTTPS Response ◄──── Gateway ◄─── WebSocket ──── Server
```

1. 客户端发送 HTTP 请求到网关 `https://{gateway_host}/api/v1/clients/{path}`
2. 网关 `ClientAuthInterceptor`（[`ClientAuthInterceptor.java`](file:///g:/workspace/cuc-ikb-ai-xunjian-repository/gateway/src/main/java/com/falcon/gateway/middleware/ClientAuthInterceptor.java)）验证 JWT（注册接口除外）
3. 网关 `ClientProxyController`（[`ClientProxyController.java`](file:///g:/workspace/cuc-ikb-ai-xunjian-repository/gateway/src/main/java/com/falcon/gateway/proxy/ClientProxyController.java)）将请求序列化为 `http_request` 隧道消息（含 method/path/headers/body(base64)）
4. 通过 WebSocket 隧道转发给服务端
5. 服务端 `TunnelClient` 接收消息，通过 `RestTemplate` 转发到本地 API `http://localhost:8080/api{path}`
6. 服务端将响应序列化为 `http_response` 消息通过隧道返回
7. 网关反序列化响应并返回给客户端

**错误处理**：
- 隧道未建立 → 网关返回 `502 Bad Gateway`
- 转发超时（默认 30s）→ 网关返回 `504 Gateway Timeout`

### 2.3 SSE 事件推送

**适用场景**：定时任务变更通知、工作流更新推送等

**流程**：

```
Client ──── GET /events/stream ──► Gateway
                                   │ 创建 SseEmitter
                                   │ 发送 sse_subscribe 隧道消息
                                   ▼
         Gateway ◄─── WebSocket ──── Server
                                   │ (TunnelEventSender 发送 sse_event)
                                   ▼
Client ◄─── SSE event ◄──────── Gateway
```

1. 客户端建立 SSE 连接到网关 `GET https://{gateway_host}/api/v1/clients/{client_id}/events/stream`
2. 网关 `SseController`（[`SseController.java`](file:///g:/workspace/cuc-ikb-ai-xunjian-repository/gateway/src/main/java/com/falcon/gateway/sse/SseController.java)）创建 `SseEmitter`，通过隧道发送 `sse_subscribe` 消息
3. 服务端需要推送事件时，通过 `TunnelEventSender` 发送 `sse_event` 消息（含 client_id/event_name/data）
4. 网关 `SseManager`（[`SseManager.java`](file:///g:/workspace/cuc-ikb-ai-xunjian-repository/gateway/src/main/java/com/falcon/gateway/sse/SseManager.java)）将事件转发到对应客户端的 SSE 连接

**广播**：服务端可发送 `sse_broadcast` 消息，网关将事件推送到所有已连接的 SSE 客户端。

### 2.4 文件上传（网关暂存 + 服务端拉取）

**适用场景**：客户端上传巡检截图等文件

**流程**：

```
Client ──── POST /uploads ───────► Gateway
                                   │ JWT 验证
                                   │ 暂存文件到 gateway.storage.dir
                                   │ 返回 {url, file_id}
                                   │ 发送 file_uploaded 隧道消息
                                   ▼
         Gateway ◄─── WebSocket ──── Server
                                   │ 收到 file_uploaded
                                   │ HTTP GET 拉取文件 (X-Tunnel-Key)
                                   ▼
         Gateway ──── HTTP 200 ────► Server (文件内容)
                                   │ 存储到服务端永久位置
                                   │ 发送 file_ack 隧道消息
                                   ▼
         Gateway (收到 file_ack，删除暂存文件)
```

1. 客户端 POST 文件到网关 `https://{gateway_host}/api/v1/clients/{client_id}/uploads`
2. 网关验证 JWT，`FileStorageService`（[`FileStorageService.java`](file:///g:/workspace/cuc-ikb-ai-xunjian-repository/gateway/src/main/java/com/falcon/gateway/storage/FileStorageService.java)）将文件暂存到 `gateway.storage.dir`，生成 file_id
3. 网关返回 `{"url": "https://{gateway_host}/api/v1/files/{file_id}", "file_id": "{uuid}"}`
4. 网关通过隧道发送 `file_uploaded` 通知服务端
5. 服务端 `TunnelClient` 收到通知后，发起 HTTP GET `https://{gateway_host}/api/v1/files/{file_id}`（携带 `X-Tunnel-Key`）拉取文件
6. 服务端存储文件到永久位置，发送 `file_ack` 消息
7. 网关收到 `file_ack` 后删除暂存文件

### 2.5 隧道消息协议

定义在 [`TunnelMessage.java`](file:///g:/workspace/cuc-ikb-ai-xunjian-repository/gateway/src/main/java/com/falcon/gateway/tunnel/TunnelMessage.java)：

| 消息类型 | 方向 | 说明 |
|---------|------|------|
| `http_request` | Gateway → Server | 客户端 HTTP 请求转发 |
| `http_response` | Server → Gateway | HTTP 响应返回 |
| `sse_event` | Server → Gateway | 定向 SSE 事件推送 |
| `sse_broadcast` | Server → Gateway | 广播 SSE 事件 |
| `sse_subscribe` | Gateway → Server | 客户端 SSE 订阅通知 |
| `sse_unsubscribe` | Gateway → Server | 客户端 SSE 断开通知 |
| `file_uploaded` | Gateway → Server | 文件上传通知 |
| `file_ack` | Server → Gateway | 文件已拉取确认 |
| `ping` | Gateway → Server | 保活探测 |
| `pong` | Server → Gateway | 保活响应 |

---

## 三、本地调试环境启动

### 3.1 环境准备

| 依赖 | 版本要求 | 说明 |
|------|---------|------|
| JDK | 17+ | 网关和服务端共用 |
| Maven | 3.6+ | 构建工具 |
| Python | >=3.11 | 客户端运行环境 |
| uv | latest | Python 依赖管理 |
| adb | - | Android 调试桥（客户端需要） |

### 3.2 配置修改

#### 网关配置

文件：[`gateway/src/main/resources/application.yml`](file:///g:/workspace/cuc-ikb-ai-xunjian-repository/gateway/src/main/resources/application.yml)

```yaml
gateway:
  tunnel:
    key: dev-tunnel-key           # 隧道认证密钥，与服务端一致
    ping-interval: 30
    request-timeout: 30
  jwt:
    secret: falcon-patrol-client-jwt-secret-key-2024   # JWT 密钥，与服务端一致
  storage:
    dir: ./uploads
    cleanup-hours: 24
    base-url: http://localhost:8080   # 网关本地访问地址
server:
  port: 8080
```

也可通过环境变量覆盖：
- `GATEWAY_TUNNEL_KEY`
- `GATEWAY_JWT_SECRET`
- `GATEWAY_STORAGE_DIR`
- `GATEWAY_STORAGE_BASE_URL`

#### 服务端配置

文件：[`falconconsole/src/main/resources/application.yml`](file:///g:/workspace/cuc-ikb-ai-xunjian-repository/falconconsole/src/main/resources/application.yml)

在 `falcon.client` 下添加：

```yaml
falcon:
  client:
    jwt-secret: falcon-patrol-client-jwt-secret-key-2024   # 与网关一致
    gateway-tunnel-url: ws://localhost:8080/api/v1/tunnel   # 网关隧道地址
    tunnel-key: dev-tunnel-key                              # 与网关一致
```

### 3.3 启动步骤

#### Step 1：启动网关

```bash
cd g:\workspace\cuc-ikb-ai-xunjian-repository\gateway
mvn clean package -DskipTests
java -jar target/gateway-1.0.0.jar
```

验证：访问 http://localhost:8080/health，应返回 `{"status":"ok","tunnel_connected":false}`

#### Step 2：启动服务端

```bash
cd g:\workspace\cuc-ikb-ai-xunjian-repository\falconconsole
mvn clean package -DskipTests
java -jar target/falconconsole-1.0.0.jar
```

验证：网关日志应显示 `隧道会话已建立`，服务端日志应显示 `隧道连接成功 | url=ws://localhost:8080/api/v1/tunnel`

再次访问 http://localhost:8080/health，应返回 `{"status":"ok","tunnel_connected":true}`

#### Step 3：启动客户端

修改 `.env` 文件，将同步服务器地址指向网关：

```bash
# .env 文件中
AUTOGLM_SERVER_URL=http://127.0.0.1:8083
```

然后启动客户端：

```bash
cd g:\workspace\AutoGLM-GUI
uv sync
uv run autoglm-gui --base-url http://localhost:8080/v1
```

> **注意**：`--base-url` 是模型 API 地址，保持不变；`AUTOGLM_SERVER_URL` 是同步服务器地址，隧道模式下需指向网关（8083）而非服务端（8080）。

### 3.4 功能验证

#### 客户端注册

1. 客户端启动后自动发起注册请求
2. 网关日志：`HTTP POST /api/v1/clients/register | status=200`
3. 服务端日志：客户端注册成功

#### SSE 事件推送

1. 在服务端管理后台触发事件（如更新定时任务）
2. 客户端日志显示收到 `scheduled_task.changed` 事件

#### 文件上传

1. 客户端上传截图
2. 网关 `uploads/` 目录出现临时文件
3. 服务端 `uploads/` 目录出现相同文件
4. 网关临时文件被自动删除（收到 `file_ack` 后）

---

## 四、常见问题排查

### 隧道连接失败

- 检查网关和服务端 `tunnel.key` 是否一致
- 验证网关是否启动：访问 `http://localhost:8080/health`
- 服务端日志搜索 `隧道连接失败`，查看具体错误原因
- 检查 `gateway-tunnel-url` 格式是否正确（`ws://` 或 `wss://`）

### JWT 验证失败

- 确保网关和服务端 `jwt.secret` 一致
- 检查客户端 token 是否过期或格式错误
- 网关日志搜索 `JWT 验证失败`

### 文件上传失败

- 检查网关 `storage.dir` 目录权限
- 验证服务端拉取文件时 `X-Tunnel-Key` 是否正确
- 网关日志搜索 `文件上传失败`，服务端日志搜索 `拉取文件失败`

### 请求超时

- 检查隧道是否已建立（`/health` 接口 `tunnel_connected` 是否为 `true`）
- 调大 `gateway.tunnel.request-timeout`（默认 30s）
- 服务端日志查看本地 API 响应时间是否过长

---

## 五、关键代码索引

| 组件 | 文件路径 |
|------|---------|
| 网关入口 | [`GatewayApplication.java`](file:///g:/workspace/cuc-ikb-ai-xunjian-repository/gateway/src/main/java/com/falcon/gateway/GatewayApplication.java) |
| 网关配置 | [`GatewayProperties.java`](file:///g:/workspace/cuc-ikb-ai-xunjian-repository/gateway/src/main/java/com/falcon/gateway/config/GatewayProperties.java) |
| 隧道管理 | [`TunnelManager.java`](file:///g:/workspace/cuc-ikb-ai-xunjian-repository/gateway/src/main/java/com/falcon/gateway/tunnel/TunnelManager.java) |
| 隧道消息协议 | [`TunnelMessage.java`](file:///g:/workspace/cuc-ikb-ai-xunjian-repository/gateway/src/main/java/com/falcon/gateway/tunnel/TunnelMessage.java) |
| 隧道 WebSocket 处理 | [`TunnelHandler.java`](file:///g:/workspace/cuc-ikb-ai-xunjian-repository/gateway/src/main/java/com/falcon/gateway/tunnel/TunnelHandler.java) |
| 客户端请求代理 | [`ClientProxyController.java`](file:///g:/workspace/cuc-ikb-ai-xunjian-repository/gateway/src/main/java/com/falcon/gateway/proxy/ClientProxyController.java) |
| JWT 认证拦截 | [`ClientAuthInterceptor.java`](file:///g:/workspace/cuc-ikb-ai-xunjian-repository/gateway/src/main/java/com/falcon/gateway/middleware/ClientAuthInterceptor.java) |
| SSE 管理 | [`SseManager.java`](file:///g:/workspace/cuc-ikb-ai-xunjian-repository/gateway/src/main/java/com/falcon/gateway/sse/SseManager.java) |
| SSE 控制器 | [`SseController.java`](file:///g:/workspace/cuc-ikb-ai-xunjian-repository/gateway/src/main/java/com/falcon/gateway/sse/SseController.java) |
| 文件暂存 | [`FileStorageService.java`](file:///g:/workspace/cuc-ikb-ai-xunjian-repository/gateway/src/main/java/com/falcon/gateway/storage/FileStorageService.java) |
| 文件下载 | [`FileStorageController.java`](file:///g:/workspace/cuc-ikb-ai-xunjian-repository/gateway/src/main/java/com/falcon/gateway/storage/FileStorageController.java) |
| 健康检查 | [`HealthController.java`](file:///g:/workspace/cuc-ikb-ai-xunjian-repository/gateway/src/main/java/com/falcon/gateway/health/HealthController.java) |
| 服务端隧道客户端 | [`TunnelClient.java`](file:///g:/workspace/cuc-ikb-ai-xunjian-repository/falconconsole/src/main/java/com/falcon/patrol/tunnel/TunnelClient.java) |
| 服务端同步控制器 | [`ClientSyncController.java`](file:///g:/workspace/cuc-ikb-ai-xunjian-repository/falconconsole/src/main/java/com/falcon/patrol/controller/ClientSyncController.java) |
| 客户端 HTTP 同步 | [`client.py`](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/sync/client.py) |
| 客户端配置管理 | [`config_manager.py`](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/config_manager.py) |
