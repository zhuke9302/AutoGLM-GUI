# PC Web 业务系统配置与任务创建优化方案

## 需求概述

1. **业务系统配置**：当终端类型为 PC Web 时，也要支持关联客户端（当前 PC Web 只配环境，不关联客户端）
2. **任务中心创建任务**：当端类型选择 PC Web 时，也要显示"目标客户端"和"巡检设备"下拉框，且设备需按端类型过滤（`serial=web-browser` 为 PC Web，其他为 App）

***

## 当前状态分析

### 业务系统配置（SystemConfig）

* **PC Web 端**：只配置环境列表（envName/executeAccount/executePassword/envUrl），不关联客户端

* **App 端**：只关联客户端（clientIds），不配环境

* 后端 `TerminalConfig` 只有 `envs`（PC Web）和 `clientIds`（App）两个字段，互斥

* 校验逻辑 `validateTerminals`：PC Web 校验 env，App 校验 clientIds，互斥

### 任务创建（TaskCreateDialog）

* **PC Web**：只显示目标环境+执行账号，无客户端和设备选择

* **App**：显示目标客户端+巡检设备

* 后端 `validateTaskReq`：仅对 APP 校验 clientId/deviceSerialnos，PC 端跳过

* 后端 `save`：PC 端自动填 `deviceSerialnos=["web-browser"]`，不存 clientId

* `runTaskNow`：PC 端通过查 `serial=web-browser` 的在线设备动态找客户端

### 关键问题

1. PC Web 没有关联客户端，导致任务执行时只能随机选一个在线的 PC Web 客户端，无法指定
2. 任务创建时 PC Web 不显示客户端/设备选择，用户无法控制任务由哪个客户端执行

***

## 改动方案

### 一、业务系统配置：PC Web 也关联客户端

#### 1.1 后端 PatrolSystemController

**文件**: `falconconsole/src/main/java/com/falcon/patrol/controller/PatrolSystemController.java`

**`TerminalConfig`** **内部类** — 无需改动，已有 `clientIds` 字段，PC Web 和 App 都可使用

**`validateTerminals`** **方法** — 修改 PC Web 分支，增加客户端关联校验：

```java
// 修改前：
if ("PC Web".equals(type)) {
    // 只校验 envs
}
// 修改后：
if ("PC Web".equals(type)) {
    // 校验 envs（保持不变）
    // 新增：校验 clientIds
    List<String> clientIds = tc.getClientIds();
    if (clientIds == null || clientIds.isEmpty()) {
        throw new IllegalArgumentException("PC Web 端类型请至少选择一个客户端");
    }
}
```

**`saveTerminals`** **方法** — 修改 PC Web 分支，同时保存 envs 和 clientIds：

```java
// 修改前：
if ("PC Web".equals(tc.getTerminalType()) && tc.getEnvs() != null) {
    systemEnvService.saveEnvs(t.getId(), tc.getEnvs());
} else if ("App".equals(tc.getTerminalType()) && tc.getClientIds() != null) {
    // 保存 terminal_clients
}
// 修改后：
if ("PC Web".equals(tc.getTerminalType())) {
    if (tc.getEnvs() != null) {
        systemEnvService.saveEnvs(t.getId(), tc.getEnvs());
    }
    if (tc.getClientIds() != null) {
        // 保存 terminal_clients（与 App 相同逻辑）
        List<PatrolSystemTerminalClient> rels = tc.getClientIds().stream().map(cid -> {
            PatrolSystemTerminalClient rel = new PatrolSystemTerminalClient();
            rel.setTerminalId(t.getId());
            rel.setClientId(cid);
            return rel;
        }).collect(Collectors.toList());
        terminalClientService.saveBatch(rels);
    }
} else if ("App".equals(tc.getTerminalType()) && tc.getClientIds() != null) {
    // 保持不变
}
```

**`detail`** **接口** — 修改 PC Web 分支，同时返回 envs 和 clients：

```java
// 修改前：
if ("PC Web".equals(t.getTerminalType())) {
    tv.setEnvs(systemEnvService.listByTerminalId(t.getId()));
} else if ("App".equals(t.getTerminalType())) {
    // 查 clients
}
// 修改后：
if ("PC Web".equals(t.getTerminalType())) {
    tv.setEnvs(systemEnvService.listByTerminalId(t.getId()));
    // 新增：也查关联的客户端
    List<PatrolSystemTerminalClient> rels = terminalClientService.listByTerminalId(t.getId());
    List<ClientSimpleVO> clients = new ArrayList<>();
    for (PatrolSystemTerminalClient rel : rels) {
        PatrolClient c = clientService.getById(rel.getClientId());
        if (c != null) {
            ClientSimpleVO csv = new ClientSimpleVO();
            csv.setId(c.getId());
            csv.setHostname(c.getHostname());
            csv.setIp(c.getIp());
            if (c.getLastHeartbeatAt() != null) {
                csv.setLastHeartbeatAt(c.getLastHeartbeatAt().toString());
            }
            clients.add(csv);
        }
    }
    tv.setClients(clients);
} else if ("App".equals(t.getTerminalType())) {
    // 保持不变
}
```

**`buildPageItems`** — 此方法批量查询时已按 terminalId 批量查 terminal\_clients，PC Web terminal 的 client 关联也会被查出来，只需确保回填逻辑正确。当前代码 `tc.setClients(...)` 只在 `t.getTerminalType().equals("App")` 时设置，需改为 PC Web 也设置。

查看 `buildPageItems` 方法中回填 clients 的逻辑：

```java
// 当前逻辑：只有 App 才回填 clients
// 修改：PC Web 也回填 clients
```

#### 1.2 前端 SystemFormDialog.vue

**文件**: `frontend/src/views/system/modules/SystemFormDialog.vue`

在 PC Web 端类型区块中，增加"关联客户端"选择（与 App 相同的 el-select），放在环境配置下方：

```html
<!-- PC Web 端：目标环境配置 -->
<template v-if="term.terminalType === 'PC Web'">
  <!-- 环境配置（保持不变） -->
  <div class="group-sub-label">目标环境配置 ...</div>
  ...

  <!-- 新增：关联客户端 -->
  <div class="group-sub-label">
    关联客户端
    <span class="group-hint">选择执行 PC Web 巡检的客户端</span>
  </div>
  <el-form-item label="" class="client-select-item">
    <el-select
      v-model="term.clientIds"
      multiple
      filterable
      placeholder="请选择客户端"
      style="width:100%"
    >
      <el-option
        v-for="c in clientStore.clients"
        :key="c.id"
        :label="`${c.hostname || '未命名'} (${c.ip || '--'})`"
        :value="c.id"
      />
    </el-select>
  </el-form-item>
</template>
```

**编辑回显** — `initEditData` 方法中，PC Web terminal 也会返回 clients 数组，需要回填 clientIds：

```js
// 当前逻辑只处理 App 的 clientIds
// 修改：PC Web 也回填 clientIds
// 代码中已有 clientIds: (t.clients || []).map(c => c.id)
// 只要后端 detail 接口返回 clients，前端无需额外修改
```

***

### 二、任务创建：PC Web 显示客户端和设备选择

#### 2.1 前端 TaskCreateDialog.vue

**文件**: `frontend/src/views/task/modules/TaskCreateDialog.vue`

**核心改动**：PC Web 区块增加"目标客户端"和"巡检设备"下拉框。

将 PC Web 区块从只显示环境配置，改为同时显示客户端和设备选择：

```html
<!-- PC Web：目标环境 + 执行账号 + 客户端 + 设备 -->
<div v-if="form.terminalType === 'PC Web'" class="form-block">
  <div class="form-title">目标环境配置</div>
  <!-- 环境配置（保持不变） -->
  ...

  <!-- 新增：客户端与设备 -->
  <div class="form-title" style="margin-top:16px">客户端与设备</div>
  <el-form :model="form" label-position="top">
    <el-row :gutter="16">
      <el-col :span="12">
        <el-form-item label="目标客户端">
          <el-select v-model="form.clientId" placeholder="请选择客户端" style="width:100%" filterable>
            <el-option
              v-for="c in store.currentClientOptions"
              :key="c.id"
              :label="`${c.hostname || '未命名'} (${c.ip || '--'}) ${isClientOnline(c) ? '[在线]' : '[离线]'}`"
              :value="c.id"
            />
          </el-select>
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="巡检设备">
          <el-select
            v-model="form.deviceSerialnos"
            placeholder="请选择设备"
            style="width:100%"
            multiple
            filterable
            :disabled="!form.clientId"
          >
            <el-option
              v-for="d in store.currentDevices"
              :key="d.id"
              :label="`${d.displayName || d.serial} (${!currentClientOnline ? '离线' : (d.status === 'online' ? '在线' : '离线')})`"
              :value="d.serial"
            />
          </el-select>
        </el-form-item>
      </el-col>
    </el-row>
  </el-form>
</div>
```

**设备过滤**：PC Web 的设备下拉只显示 `serial=web-browser` 的设备。有两种实现方式：

* **方案 A（前端过滤）**：在 `loadDevicesByClient` 返回的设备列表中，根据当前 `form.terminalType` 过滤。PC Web 只显示 `serial === 'web-browser'` 的设备，App 只显示 `serial !== 'web-browser'` 的设备。

* **方案 B（后端过滤）**：新增 API 参数，按端类型过滤设备。

选择**方案 A**（前端过滤），因为数据量小，无需新增 API。

具体实现：在模板中用 computed 或内联过滤：

```html
<!-- PC Web 设备过滤 -->
<el-option
  v-for="d in store.currentDevices.filter(d => d.serial === 'web-browser')"
  .../>
<!-- App 设备过滤 -->
<el-option
  v-for="d in store.currentDevices.filter(d => d.serial !== 'web-browser')"
  .../>
```

**客户端选择联动**：PC Web 选了客户端后，也要调 `loadDevicesByClient` 加载设备列表。需要修改 `watch(form.clientId)` 的条件，不再限制只在 App 时触发：

```js
// 修改前：只在 App 时加载设备
watch(() => form.clientId, (val) => {
  if (form.terminalType === 'App' && val) {
    store.loadDevicesByClient(val)
    ...
  }
})
// 修改后：App 和 PC Web 都加载设备
watch(() => form.clientId, (val) => {
  if (val) {
    store.loadDevicesByClient(val)
    form.deviceSerialnos = []
  }
})
```

**提交校验** — 修改 `handleSubmit`，PC Web 也校验 clientId 和 deviceSerialnos：

```js
if (form.terminalType === 'PC Web') {
  if (!form.targetEnv) { ... }
  if (!form.executeAccount.trim()) { ... }
  // 新增
  if (!form.clientId) {
    ElMessage.warning('请选择客户端')
    return
  }
  if (!form.deviceSerialnos || form.deviceSerialnos.length === 0) {
    ElMessage.warning('请至少选择一个设备')
    return
  }
}
```

#### 2.2 前端 task store

**文件**: `frontend/src/stores/task.js`

**`buildSubmitData`** — PC Web 分支也传递 clientId 和 deviceSerialnos：

```js
// 修改前：
if (data.terminalType === 'PC Web' || data.terminalType === 'PC') {
  submitData.terminalType = 'PC'
  submitData.executeAccount = data.executeAccount || ''
  submitData.targetEnv = data.targetEnv || ''
}
// 修改后：
if (data.terminalType === 'PC Web' || data.terminalType === 'PC') {
  submitData.terminalType = 'PC'
  submitData.executeAccount = data.executeAccount || ''
  submitData.targetEnv = data.targetEnv || ''
  submitData.clientId = data.clientId || ''
  submitData.deviceSerialnos = Array.isArray(data.deviceSerialnos) && data.deviceSerialnos.length
    ? JSON.stringify(data.deviceSerialnos)
    : (typeof data.deviceSerialnos === 'string' ? data.deviceSerialnos : null)
}
```

**`loadSystemDetail`** — PC Web terminal 的 clients 也要加载到 `currentClientOptions`：

```js
// 修改前：
const pcWeb = terminals.find(t => t.terminalType === 'PC Web')
currentEnvOptions.value = pcWeb?.envs || []
const app = terminals.find(t => t.terminalType === 'App')
currentClientOptions.value = app?.clients || []

// 修改后：
const pcWeb = terminals.find(t => t.terminalType === 'PC Web')
currentEnvOptions.value = pcWeb?.envs || []
const app = terminals.find(t => t.terminalType === 'App')
// 根据当前选择的端类型加载对应的客户端
// PC Web 和 App 都可能有 clients
currentClientOptions.value = (form.terminalType === 'PC Web' ? pcWeb?.clients : app?.clients) || []
```

但 `loadSystemDetail` 在选系统时调用，此时还没选端类型。更好的方案是**预加载所有端类型的 clients**，在端类型切换时使用：

```js
// 修改后：
const pcWeb = terminals.find(t => t.terminalType === 'PC Web')
currentEnvOptions.value = pcWeb?.envs || []
currentPcWebClients.value = pcWeb?.clients || []  // 新增
const app = terminals.find(t => t.terminalType === 'App')
currentAppClients.value = app?.clients || []       // 重命名
currentClientOptions.value = []  // 端类型选择后再填充
```

或者更简单的方案：在 `loadSystemDetail` 中同时加载 PC Web 和 App 的 clients，存入不同变量，在端类型切换时赋值给 `currentClientOptions`。

**更简洁的方案**：`currentClientOptions` 在端类型切换时赋值。新增两个缓存变量：

```js
const pcWebClientOptions = ref([])
const appClientOptions = ref([])

// loadSystemDetail 中：
pcWebClientOptions.value = pcWeb?.clients || []
appClientOptions.value = app?.clients || []

// 端类型切换时：
watch(() => form.terminalType, (val) => {
  if (val === 'PC Web') {
    store.currentClientOptions = store.pcWebClientOptions
  } else if (val === 'App') {
    store.currentClientOptions = store.appClientOptions
  }
  // 清空 clientId 和 deviceSerialnos
})
```

#### 2.3 后端 PatrolScheduledTaskController

**文件**: `falconcontroller/src/main/java/com/falcon/patrol/controller/PatrolScheduledTaskController.java`

**`validateTaskReq`** — PC Web 也校验 clientId 和 deviceSerialnos：

```java
// 修改前：
if (!TerminalType.isApp(taskReq.getTerminalType())) {
    return null;  // PC 端跳过校验
}
// 修改后：
if (TerminalType.isPc(taskReq.getTerminalType())) {
    // PC Web 校验
    if (!StringUtils.hasText(taskReq.getClientId())) {
        return Result.error(400, "客户端ID不能为空");
    }
    if (!StringUtils.hasText(taskReq.getDeviceSerialnos())) {
        return Result.error(400, "目标设备序列号不能为空");
    }
    if (!StringUtils.hasText(taskReq.getCronExpression())) {
        return Result.error(400, "Cron 表达式不能为空");
    }
    if (CollectionUtils.isEmpty(taskReq.getWorkflowList())) {
        return Result.error(400, "操作步骤不能为空");
    }
    if (!StringUtils.hasText(taskReq.getOwner())) {
        return Result.error(400, "责任人不能为空");
    }
    return null;
}
// APP 校验保持不变
```

**`save`** **方法** — PC Web 任务的 `deviceSerialnos` 不再自动填充，改为前端传入。移除自动填充逻辑：

```java
// 修改前：
if (TerminalType.isPc(task.getTerminalType())) {
    if (!StringUtils.hasText(task.getDeviceSerialnos())) {
        task.setDeviceSerialnos("[\"web-browser\"]");
    }
}
// 修改后：删除此段，前端会传入 clientId 和 deviceSerialnos
```

#### 2.4 后端 PatrolScheduledTaskServiceImpl

**文件**: `falconconsole/src/main/java/com/falcon/patrol/service/impl/PatrolScheduledTaskServiceImpl.java`

**`runTaskNow`** — PC Web 任务使用 task 上存储的 clientId，不再动态查找：

```java
// 修改前：PC 任务查 serial=web-browser 的在线设备找 clientId
// 修改后：PC 任务直接用 task.getClientId()
if (TerminalType.isPc(task.getTerminalType())) {
    String clientId = task.getClientId();
    if (!StringUtils.hasText(clientId)) {
        throw new BusinessException(400, "PC Web 任务未指定客户端");
    }
    PatrolClient client = clientService.getById(clientId);
    if (client == null || !clientStatusService.isClientOnline(client)) {
        throw new BusinessException(400, "PC Web 客户端离线，无法执行任务");
    }
    String fireId = UUID.randomUUID().toString();
    Map<String, Object> eventData = new HashMap<>();
    eventData.put("scheduled_task_id", taskId);
    eventData.put("fire_id", fireId);
    eventData.put("device_serialnos", parseDeviceSerialnos(task.getDeviceSerialnos()));
    eventSender.sendToClient(clientId, "TASK_DISPATCH", eventData);
    return fireId;
}
```

***

## 改动文件清单

| 文件                                                       | 改动内容                                                                                                                                                          |
| -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `falconconsole/.../PatrolSystemController.java`          | `validateTerminals` PC Web 增加 clientIds 校验；`saveTerminals` PC Web 同时保存 envs 和 clients；`detail` PC Web 同时返回 envs 和 clients；`buildPageItems` PC Web 也回填 clients |
| `frontend/src/views/system/modules/SystemFormDialog.vue` | PC Web 区块增加"关联客户端"下拉                                                                                                                                          |
| `frontend/src/views/task/modules/TaskCreateDialog.vue`   | PC Web 区块增加"目标客户端"和"巡检设备"下拉；设备按端类型过滤；clientId 联动加载设备；提交校验增加 clientId/deviceSerialnos                                                                          |
| `frontend/src/stores/task.js`                            | `buildSubmitData` PC Web 也传 clientId/deviceSerialnos；`loadSystemDetail` 分别缓存 PC Web 和 App 的 clients；端类型切换时赋值 currentClientOptions                             |
| `falconconsole/.../PatrolScheduledTaskController.java`   | `validateTaskReq` PC Web 也校验；`save` 移除自动填充 deviceSerialnos                                                                                                    |
| `falconconsole/.../PatrolScheduledTaskServiceImpl.java`  | `runTaskNow` PC Web 用 task.clientId 而非动态查找                                                                                                                    |

***

## 验证步骤

1. **业务系统配置**：创建/编辑系统，PC Web 端类型可关联客户端，保存后详情返回 clients
2. **任务创建**：选 PC Web 端类型后，显示环境+客户端+设备下拉；设备只显示 web-browser；提交后 clientId 和 deviceSerialnos 正确存储
3. **任务执行**：PC Web 任务 `runTaskNow` 使用存储的 clientId 推送 SSE
4. **编辑回显**：编辑 PC Web 任务时，clientId 和 deviceSerialnos 正确回显
5. **App 任务不受影响**：App 端的创建、执行、回显逻辑不变

