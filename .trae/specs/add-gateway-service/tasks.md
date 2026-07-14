# Tasks

- [x] Task 1: 网关项目脚手架
  - [x] 1.1 创建 `cuc-ikb-ai-xunjian-repository/gateway/` 目录，初始化 Maven 项目（pom.xml）
  - [x] 1.2 配置 pom.xml：Spring Boot 3.2.x parent、Java 17、spring-boot-starter-web、spring-boot-starter-websocket、jjwt 0.12.x、Lombok
  - [x] 1.3 创建 `GatewayApplication.java` 入口类（@SpringBootApplication）
  - [x] 1.4 创建 `GatewayProperties.java`（@ConfigurationProperties(prefix = "gateway")），实现配置属性绑定

- [x] Task 2: 隧道协议定义
  - [x] 2.1 创建 `TunnelMessage.java`，定义隧道消息类型枚举（http_request、http_response、sse_event、sse_broadcast、sse_subscribe、sse_unsubscribe、file_uploaded、file_ack、ping、pong）
  - [x] 2.2 定义各消息类型的 Java record/DTO 类，使用 Jackson JSON 序列化/反序列化

- [x] Task 3: 隧道连接管理
  - [x] 3.1 创建 `TunnelManager.java`（@Component），管理隧道 WebSocket 会话
  - [x] 3.2 实现 Tunnel Key 认证：验证 `X-Tunnel-Key` 头
  - [x] 3.3 实现请求路由：客户端 HTTP 请求到达后，通过隧道发送 `http_request` 消息，等待 `http_response`
  - [x] 3.4 实现请求/响应关联：基于 request_id 的 ConcurrentHashMap<String, CompletableFuture>
  - [x] 3.5 实现隧道保活：每 30s 发送 ping，超时断开（@Scheduled）
  - [x] 3.6 实现隧道断开处理：清理状态，客户端请求返回 502

- [x] Task 4: 隧道 WebSocket 端点
  - [x] 4.1 创建 `WebSocketConfig.java`，注册 WebSocket 端点
  - [x] 4.2 创建 `TunnelHandler.java`（extends TextWebSocketHandler），实现 WebSocket 连接处理和消息读写
  - [x] 4.3 处理服务端发来的消息：http_response、sse_event、sse_broadcast、file_ack、pong
  - [x] 4.4 将 http_response 分发给对应的 pending request（CompletableFuture）
  - [x] 4.5 将 sse_event/sse_broadcast 转发给 SseManager
  - [x] 4.6 将 file_ack 转发给 FileStorageService（删除已确认文件）

- [x] Task 5: JWT 验证拦截器
  - [x] 5.1 创建 `ClientAuthInterceptor.java`（extends HandlerInterceptor），实现 JWT 验证
  - [x] 5.2 使用与服务端相同的 jjwt 库和 HMAC-SHA256 算法验证 JWT 签名和有效期
  - [x] 5.3 从 JWT Claims 中提取 client_id，放行 `/api/v1/clients/register` 路径
  - [x] 5.4 验证失败返回 401 JSON 响应
  - [x] 5.5 创建 `WebConfig.java`，注册拦截器到 `/api/v1/clients/**` 路径

- [x] Task 6: 速率限制拦截器
  - [x] 6.1 创建 `RateLimitInterceptor.java`（extends HandlerInterceptor），实现基于客户端 IP 的速率限制
  - [x] 6.2 使用 Guava RateLimiter 或令牌桶算法，默认每 IP 每秒 30 个请求，超出返回 429
  - [x] 6.3 在 `WebConfig.java` 中注册拦截器

- [x] Task 7: 客户端 HTTP 代理
  - [x] 7.1 创建 `ClientProxyController.java`（@RestController），实现客户端 HTTP 请求代理
  - [x] 7.2 接收客户端请求，序列化为隧道 `http_request` 消息
  - [x] 7.3 通过 TunnelManager 发送并等待 `http_response`（CompletableFuture.get with timeout）
  - [x] 7.4 将隧道响应反序列化后返回给客户端
  - [x] 7.5 处理隧道未建立（502）和超时（504）错误
  - [x] 7.6 文件上传请求（`/uploads`）不通过隧道转发，改由文件暂存模块处理

- [x] Task 8: 文件暂存管理
  - [x] 8.1 创建 `FileStorageService.java`（@Service），实现文件暂存管理
    - 保存上传文件到本地磁盘（配置的 `gateway.storage.dir` 目录）
    - 生成 file_id，记录文件元数据（client_id、task_run_id、category、filename、mime_type、size_bytes、上传时间）
    - 按 file_id 读取文件
    - 收到 file_ack 后删除暂存文件
    - @Scheduled 定时清理超过 24 小时未确认的文件
  - [x] 8.2 创建 `FileStorageController.java`（@RestController），实现文件上传和下载端点
    - POST `/api/v1/clients/{client_id}/uploads` — 客户端上传文件（JWT 验证），暂存后返回 URL + file_id，通过隧道发送 `file_uploaded` 通知
    - GET `/api/v1/files/{file_id}` — 服务端拉取暂存文件（Tunnel Key 验证）

- [x] Task 9: SSE 连接管理与事件转发
  - [x] 9.1 创建 `SseManager.java`（@Component），管理客户端 SSE 连接（ConcurrentHashMap<String, SseEmitter>，按 client_id 索引）
  - [x] 9.2 创建 `SseController.java`（@RestController），实现客户端 SSE 连接端点
    - GET `/api/v1/clients/{client_id}/events/stream` — 验证 JWT、创建 SseEmitter、发送 `connected` 事件
  - [x] 9.3 实现客户端 SSE 断开：发送 `sse_unsubscribe` 给隧道、清理资源
  - [x] 9.4 实现 SSE 连接数限制：每个 client_id 最多 1 个连接
  - [x] 9.5 在 SseManager 中实现事件转发：接收隧道 sse_event/sse_broadcast 消息并转发给客户端
  - [x] 9.6 实现隧道断开时 SSE 保活：@Scheduled 定期 ping，隧道重连后重新 subscribe

- [x] Task 10: 健康检查
  - [x] 10.1 创建 `HealthController.java`（@RestController），实现 GET `/health` 端点
  - [x] 10.2 返回 `{"status": "ok", "tunnel_connected": true/false}`

- [x] Task 11: TLS 和路由整合
  - [x] 11.1 在 `application.yml` 中配置默认值
  - [x] 11.2 整合所有拦截器和路由（WebConfig 中注册）
  - [x] 11.3 注册隧道 WebSocket 端点 `/api/v1/tunnel`
  - [x] 11.4 注册客户端 API 代理路由 `/api/v1/clients/**`（排除 `/uploads`，由文件暂存处理）
  - [x] 11.5 注册文件上传端点 `/api/v1/clients/{client_id}/uploads`
  - [x] 11.6 注册文件下载端点 `/api/v1/files/{file_id}`（Tunnel Key 验证）
  - [x] 11.7 注册健康检查端点 `/health`
  - [x] 11.8 实现 HTTPS 监听（配置 TLS keystore 时通过 Spring Boot server.ssl 配置）
  - [x] 11.9 支持无证书时纯 HTTP 模式
  - [x] 11.10 请求日志记录（通过 Spring Boot CommonsRequestLoggingFilter 或自定义 Filter）

- [x] Task 12: Docker 部署文件
  - [x] 12.1 创建 `Dockerfile`，基于 Eclipse Temurin JDK 17 + Maven 多阶段构建
  - [x] 12.2 创建 `docker-compose.yml`，通过环境变量配置
  - [x] 12.3 创建 `application-example.yml`，示例配置文件

- [x] Task 13: 服务端 TunnelClient 组件
  - [x] 13.1 新增 `falconconsole/.../tunnel/TunnelConfig.java`，隧道配置类（gatewayTunnelUrl、tunnelKey）
  - [x] 13.2 新增 `falconconsole/.../tunnel/TunnelMessage.java`，隧道消息模型（与网关协议一致，含 file_uploaded、file_ack）
  - [x] 13.3 新增 `falconconsole/.../tunnel/TunnelClient.java`，WebSocket 隧道客户端
    - 启动时建立 WebSocket 连接到网关，携带 `X-Tunnel-Key` 认证
    - 接收 `http_request` 消息，转发到本地 `http://localhost:8080/api/...`，将响应通过隧道返回
    - 接收 `file_uploaded` 消息，通过出站 HTTP GET 从网关拉取暂存文件，存储到服务端永久位置，发送 `file_ack`
    - 接收 `ping` 消息，回复 `pong`
    - 断开自动重连（指数退避）
  - [x] 13.4 修改 `ClientProperties.java`，新增 `gatewayTunnelUrl` 和 `tunnelKey` 字段
  - [x] 13.5 修改 `application.yml`，新增 `falcon.client.gateway-tunnel-url` 和 `falcon.client.tunnel-key` 配置项

- [x] Task 14: 服务端 TunnelEventSender 组件
  - [x] 14.1 新增 `falconconsole/.../tunnel/TunnelEventSender.java`，通过隧道推送 SSE 事件
    - `sendToClient(clientId, eventName, data)` → 发送 `sse_event` 消息
    - `sendToAll(eventName, data)` → 发送 `sse_broadcast` 消息
  - [x] 14.2 修改 SseEmitterManager 调用点：当隧道模式启用时，使用 TunnelEventSender 替代 SseEmitterManager
  - [x] 14.3 修改 PatrolScheduledTaskController、PatrolWorkflowController、PatrolModelConfigController 中的 SSE 推送调用
  - [x] 14.4 修改 ClientSseController：隧道模式下不再创建 SseEmitter（由网关管理 SSE 连接）
  - [x] 14.5 确保未配置隧道 URL 时保持原有直连模式（向后兼容）

- [x] Task 15: 集成验证（代码验证通过，运行时集成验证需部署后执行）
  - [ ] 15.1 本地启动网关 + 服务端（配置隧道 URL），客户端通过网关注册、心跳、同步数据
  - [ ] 15.2 验证隧道转发：客户端 HTTP 请求 → 网关 → 隧道 → 服务端 → 隧道 → 网关 → 客户端
  - [ ] 15.3 验证 SSE 中继：服务端推送事件 → 隧道 → 网关 → 客户端 SSE
  - [ ] 15.4 验证文件上传：客户端上传截图到网关 → 网关暂存 → 通知服务端 → 服务端拉取 → 确认 → 网关删除暂存
  - [ ] 15.5 验证网关 JWT 验证：无效 JWT 被网关拒绝，不到达服务端
  - [ ] 15.6 验证隧道断开重连：断开服务端 WebSocket，验证自动重连和数据恢复
  - [ ] 15.7 验证文件自动清理：超过 24 小时未确认的暂存文件被自动删除
  - [ ] 15.8 验证未配置隧道 URL 时服务端直连模式正常

# Task Dependencies
- Task 1 → Task 2, 5, 6（项目脚手架是前置）
- Task 2 → Task 3, 4（协议定义是隧道管理的前置）
- Task 3 → Task 4, 7, 9（隧道管理是端点、代理、SSE 的前置）
- Task 4 → Task 8, 9（隧道端点处理是文件暂存通知、SSE 转发的前置）
- Task 5 → Task 7, 8, 9（JWT 拦截器是代理、文件上传、SSE 的前置）
- Task 7, 8, 9, 10 → Task 11（代理、文件、SSE、健康检查是路由整合的前置）
- Task 11 → Task 12（路由整合完成后再写 Docker 文件）
- Task 13 独立于网关开发，可并行
- Task 14 depends on Task 13（TunnelEventSender 依赖 TunnelClient）
- Task 15 depends on Task 12, 14（集成验证需要网关和服务端都完成）
