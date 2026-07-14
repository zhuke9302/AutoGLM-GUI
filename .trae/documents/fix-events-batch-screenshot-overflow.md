# 修复 events/batch 截图数据导致 WebSocket 缓冲区溢出

## 问题分析

### 根因

events/batch 请求中 step 事件包含截图 base64 数据（单张 1-3MB），批量 50 个事件可达 50-150MB。
该请求通过 WebSocket 隧道传输（body 经 Base64 编码再 JSON 序列化），远超 8MB 缓冲区限制，
触发 `CloseStatus[code=1009, reason=The decoded text message was too big for the output buffer]`，
导致 WebSocket 连接断开、后续请求全部 502。

### 当前数据流（有问题）

```
Python客户端 → HTTP POST events/batch(含截图base64, 可能50MB+)
  → 网关 ClientProxyController → WebSocket隧道(整个body Base64编码)
  → falconconsole TunnelClient → 本地HTTP转发
  → ClientSyncController.batchEvents() → extractScreenshotToS3()
```

## 修改方案：网关新增 S3 上传服务，Python 端预上传截图

### 核心思路

1. 网关新增 S3 上传端点，Python 客户端直接调用网关上传截图到 S3，获取 S3 URL
2. events/batch 中用 `screenshot_url`（S3 URL）替代 `screenshot`（base64），请求轻量化
3. falconconsole 的 `extractScreenshotToS3()` 发现无 `screenshot` 字段时跳过（`screenshot_url` 已设置）

### 修改后的数据流

```
1. Python客户端 → HTTP POST /api/v1/clients/{id}/screenshots/upload (multipart, 不走隧道)
   → 网关 ScreenshotController → S3Service → 上传到S3 → 返回 S3 URL

2. Python客户端 → HTTP POST events/batch (轻量, 只有screenshot_url=S3 URL)
   → 网关 → WebSocket隧道(几KB) → falconconsole
   → ClientSyncController.batchEvents() → extractScreenshotToS3() 发现无 screenshot, 跳过
```

## 具体修改

### 1. 网关：新增 S3 依赖 — `gateway/pom.xml`

添加 AWS S3 SDK v1 依赖（与 falconconsole 保持一致）：

```xml
<!-- AWS S3 SDK -->
<dependency>
    <groupId>com.amazonaws</groupId>
    <artifactId>aws-java-sdk-s3</artifactId>
    <version>1.12.715</version>
</dependency>
```

### 2. 网关：新增 S3 配置属性 — `GatewayProperties.java`

在 `GatewayProperties` 中新增 `S3` 内部类：

```java
/** S3 对象存储配置 */
private S3 s3 = new S3();

@Data
public static class S3 {
    /** S3 兼容服务端点（如 http://localhost:9000） */
    private String endpoint;
    /** 是否使用 path-style 访问（MinIO/Ceph 设 true） */
    private boolean pathStyleAccess = true;
    /** 访问密钥 */
    private String accessKey;
    /** 秘密密钥 */
    private String secretKey;
    /** 默认存储桶 */
    private String bucket = "patrol";
    /** 区域 */
    private String region;
}
```

### 3. 网关：新增 S3 配置 — `application.yml`

```yaml
gateway:
  s3:
    endpoint: ${GATEWAY_S3_ENDPOINT:http://localhost:9000}
    path-style-access: true
    access-key: ${GATEWAY_S3_ACCESS_KEY:minioadmin}
    secret-key: ${GATEWAY_S3_SECRET_KEY:minioadmin}
    bucket: ${GATEWAY_S3_BUCKET:patrol}
    region: ${GATEWAY_S3_REGION:}
```

### 4. 网关：新增 S3Service — `gateway/src/main/java/com/falcon/gateway/storage/S3Service.java`

与 falconconsole 的 `S3Service` 接口一致：

```java
public interface S3Service {
    String upload(String objectName, byte[] data, String contentType);
}
```

### 5. 网关：新增 S3ServiceImpl — `gateway/src/main/java/com/falcon/gateway/storage/S3ServiceImpl.java`

复用 falconconsole 的 `S3ServiceImpl` 逻辑，使用 `GatewayProperties.S3` 配置。
当 S3 未配置（endpoint 为空）时，`@PostConstruct init()` 跳过初始化，`upload()` 抛出异常。

### 6. 网关：新增截图上传端点 — `gateway/src/main/java/com/falcon/gateway/storage/ScreenshotController.java`

```java
@Slf4j
@RestController
public class ScreenshotController {

    private final S3Service s3Service;

    @PostMapping("/api/v1/clients/{client_id}/screenshots/upload")
    public ResponseEntity<Map<String, String>> uploadScreenshot(
            @PathVariable("client_id") String clientId,
            @RequestParam("file") MultipartFile file,
            @RequestParam(value = "task_run_id", required = false) String taskRunId,
            @RequestParam(value = "seq", required = false) Integer seq) {

        // 构建S3对象路径: screenshots/{taskRunId}/step_{seq}.png
        String objectName = "screenshots/" + (taskRunId != null ? taskRunId : "unknown")
                          + "/step_" + (seq != null ? seq : System.currentTimeMillis()) + ".png";

        String s3Url = s3Service.upload(objectName, file.getBytes(), "image/png");

        return ResponseEntity.ok(Map.of(
            "url", s3Url,
            "object_name", objectName
        ));
    }
}
```

注意：此端点路径 `/api/v1/clients/{client_id}/screenshots/upload` 需要在 `ClientProxyController` 中排除，
不走 WebSocket 隧道代理（类似 `/uploads` 和 `/events/stream` 的处理方式）。

### 7. 网关：排除截图上传路径 — `ClientProxyController.java`

在 `proxyRequest()` 方法的路径排除逻辑中，新增 `/screenshots/upload` 排除：

```java
// 已有排除: /uploads, /events/stream
// 新增排除: /screenshots/upload
if (path.endsWith("/screenshots/upload")) {
    // 由 ScreenshotController 直接处理，不走隧道
    return;
}
```

### 8. Python 客户端：新增截图上传方法 — `AutoGLM_GUI/sync/client.py`

在 `ServerClient` 中新增 `upload_screenshot_to_s3()` 方法：

```python
async def upload_screenshot_to_s3(
    self, image_data: bytes, task_run_id: str, seq: int,
    filename: str = "screenshot.png",
) -> str | None:
    """POST /api/v1/clients/{client_id}/screenshots/upload (multipart)"""
    self._require_registered()
    if self._client is None:
        raise RuntimeError("Client is not started")

    files = {"file": (filename, image_data, "image/png")}
    data = {"task_run_id": task_run_id, "seq": str(seq)}

    resp = await self._request_raw(
        "POST",
        f"/api/v1/clients/{self._client_id}/screenshots/upload",
        files=files,
        data=data,
    )
    result = resp.json()
    return result.get("url")
```

### 9. Python 客户端：修改 `task_reporter.py`

**修改 `report_task_events()` 方法**，在构造 batch 之前提取截图并预上传：

```python
async def report_task_events(self, task_id: str) -> bool:
    # ... 现有逻辑获取 events ...

    for i in range(0, len(events), self._batch_size):
        batch = events[i : i + self._batch_size]
        items = []
        for evt in batch:
            payload = evt.get("payload")
            if isinstance(payload, dict):
                payload = await self._extract_screenshot(task_id, evt.get("seq"), payload)
            item = TaskEventBatchItem(
                seq=evt["seq"],
                event_type=evt["event_type"],
                role=evt.get("role"),
                payload=payload if isinstance(payload, dict) else {},
                created_at=evt.get("created_at", ""),
            )
            items.append(item)
        # ... 发送 batch ...
```

**新增 `_extract_screenshot()` 方法**：

```python
async def _extract_screenshot(self, task_id: str, seq: int | None, payload: dict) -> dict:
    """将 step 事件中的截图 base64 预上传到网关 S3，替换为 screenshot_url。"""
    screenshot_b64 = payload.get("screenshot")
    if not screenshot_b64 or not isinstance(screenshot_b64, str):
        return payload
    try:
        image_bytes = base64.b64decode(screenshot_b64)
        url = await self._client.upload_screenshot_to_s3(
            image_bytes, task_id, seq or 0
        )
        if url:
            new_payload = {k: v for k, v in payload.items() if k != "screenshot"}
            new_payload["screenshot_url"] = url
            return new_payload
    except Exception as e:
        logger.warning("截图预上传S3失败，保留原始数据 | task=%s | error=%s", task_id, e)
    return payload
```

### 10. Falconconsole：`extractScreenshotToS3()` 无需修改

Python 端已将 `screenshot` 替换为 `screenshot_url`，
`extractScreenshotToS3()` 检查 `payload.get("screenshot")` 为 null 时直接返回原 payload，
`screenshot_url` 已由网关 S3 上传设置。可保留作为兜底（万一旧版客户端仍发 base64）。

## 修改文件清单

| # | 项目 | 文件 | 操作 |
|---|------|------|------|
| 1 | gateway | `pom.xml` | 新增 AWS S3 SDK 依赖 |
| 2 | gateway | `config/GatewayProperties.java` | 新增 S3 配置内部类 |
| 3 | gateway | `resources/application.yml` | 新增 gateway.s3 配置段 |
| 4 | gateway | `storage/S3Service.java` | 新增 S3 服务接口 |
| 5 | gateway | `storage/S3ServiceImpl.java` | 新增 S3 服务实现 |
| 6 | gateway | `storage/ScreenshotController.java` | 新增截图上传端点 |
| 7 | gateway | `proxy/ClientProxyController.java` | 排除 /screenshots/upload 路径 |
| 8 | Python | `sync/client.py` | 新增 upload_screenshot_to_s3() |
| 9 | Python | `sync/task_reporter.py` | 新增 _extract_screenshot()，修改 report_task_events() |

## 不修改的文件

| 文件 | 原因 |
|------|------|
| `WebSocketConfig.java` | 8MB 缓冲区对轻量 batch 足够 |
| `TunnelClient.java` | 8MB 缓冲区对轻量 batch 足够 |
| `TunnelManager.java` | 隧道逻辑不变 |
| `ClientSyncController.java` | extractScreenshotToS3() 作为兜底保留 |
| `schemas.py` | payload 是 dict，已支持 screenshot_url |

## 验证步骤

1. 启动 S3 服务（MinIO）+ 网关 + falconconsole + Python 客户端
2. 执行一次巡检任务，产生含截图的 step 事件
3. 观察日志：
   - Python 端应打印截图预上传 S3 成功日志
   - 网关端应收到 `/screenshots/upload` 请求（不走隧道）
   - 网关端应收到轻量的 `/events/batch` 请求（走隧道）
   - 不再出现 `CloseStatus[code=1009]` 错误
4. 检查 S3 存储桶中是否有截图文件
5. 检查数据库 `patrol_task_events` 表，step 事件 payload 应包含 `screenshot_url`（S3 URL）
