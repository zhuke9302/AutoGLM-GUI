# 断言决策模型保底策略实施计划

## 概述

当模型偶现不出 `PASS`/`FAIL` 关键字时，在 `else` 分支中引入"决策模型"做二次断言判断。同时在模型配置管理中增加"视觉模型"和"决策模型"的区分。

## 当前状态分析

### 数据库
- `patrol_model_configs` 表无 `config_type` 字段，无法区分视觉/决策模型
- `getEffective(clientId)` 只返回一条配置（LIMIT 1）

### 服务端
- `PatrolModelConfig` 实体：clientId, baseUrl, modelName, apiKey, agentType, defaultMaxSteps
- `ClientSyncController.getConfig()` 只返回一组模型配置给客户端
- `ServerConfigResponse` 只有一组：base_url, model_name, api_key, agent_type, default_max_steps

### 客户端
- `SyncPull._apply_server_config()` 只处理一组视觉模型配置
- `UnifiedConfigManager` 只管理一组模型配置
- `task_manager.py` 和 `scheduler_manager.py` 断言解析只用 keyword 匹配，`else` 分支保守按 FAIL 处理

### 前端
- `ModelConfigFormDialog.vue` 单表单，无 tab 切换

## 实施步骤

### Step 1: 数据库 — 给 patrol_model_configs 加 config_type 字段

**文件**: `schema.sql`

在 `patrol_model_configs` 表定义中新增：
```sql
`config_type` VARCHAR(20) NOT NULL DEFAULT 'vision' COMMENT '配置类型：vision-视觉模型 / decision-决策模型',
```

**迁移 SQL**（已有数据库执行）：
```sql
ALTER TABLE patrol_model_configs ADD COLUMN config_type VARCHAR(20) NOT NULL DEFAULT 'vision' COMMENT '配置类型：vision/decision' AFTER client_id;
```

**原因**: 同一个 clientId 下可以有两条记录：一条 vision（必填），一条 decision（非必填）。

---

### Step 2: 后端实体 — PatrolModelConfig 加 configType 字段

**文件**: `PatrolModelConfig.java`

新增字段：
```java
/** 配置类型：vision-视觉模型 / decision-决策模型 */
private String configType;
```

---

### Step 3: 后端 Service — 支持按 configType 查询

**文件**: `PatrolModelConfigServiceImpl.java`

- `getEffective(clientId)` 改名为 `getEffectiveByType(clientId, configType)`，增加 `eq(configType)` 条件
- 新增 `getEffectiveVision(clientId)` → 调用 `getEffectiveByType(clientId, "vision")`
- 新增 `getEffectiveDecision(clientId)` → 调用 `getEffectiveByType(clientId, "decision")`，可返回 null

---

### Step 4: 后端 Controller — pullConfig 返回决策模型

**文件**: `ClientSyncController.java` 的 `getConfig()` 方法

返回值从单组模型配置改为包含两组：
- `base_url`, `model_name`, `api_key`, `agent_type`, `default_max_steps`（视觉模型，不变）
- 新增 `decision_base_url`, `decision_model_name`, `decision_api_key`（决策模型，可为 null）

---

### Step 5: 前端 — 模型配置表单加 tab 页签

**文件**: `ModelConfigFormDialog.vue`

- 表单上部加 `el-tabs`，两个 tab："视觉模型"（必填）、"决策模型"（非必填）
- 视觉模型 tab：modelName, baseUrl, apiKey（现有字段）
- 决策模型 tab：modelName, baseUrl, apiKey（新字段，独立输入框）
- 保存时同时提交两条记录（一条 config_type=vision，一条 config_type=decision）
- 编辑时分别加载两条记录填充两个 tab

**文件**: `ModelConfigView.vue` 列表页

- 表格中增加"配置类型"列显示 vision/decision

---

### Step 6: 客户端同步 — ServerConfigResponse 增加决策模型

**文件**: `sync/schemas.py`

`ServerConfigResponse` 新增：
```python
decision_base_url: str | None = None
decision_model_name: str | None = None
decision_api_key: str | None = None
```

**文件**: `sync/sync_pull.py`

`_apply_server_config()` 增加决策模型字段提取和写入。

---

### Step 7: 客户端配置 — UnifiedConfigManager 支持决策模型

**文件**: `config_manager.py`

- `ConfigModel` 新增 `decision_base_url`, `decision_model_name`, `decision_api_key` 字段（均为 Optional）
- `set_server_config()` 支持写入决策模型配置

---

### Step 8: 客户端断言 — else 分支用决策模型做二次判断

**文件**: `task_manager.py`（两处）和 `scheduler_manager.py`（一处）

在断言解析的 `else` 分支中，当 keyword 匹配失败时：
1. 从 config_manager 获取决策模型配置
2. 如果有决策模型，构造一个轻量 prompt 调用决策模型判断断言是否成立
3. 如果没有决策模型，保持原有逻辑（保守按 FAIL 处理）

新增辅助函数 `_judge_assertion_with_decision_model()`：
```python
async def _judge_assertion_with_decision_model(
    assertion_name: str, agent_message: str
) -> bool | None:
    """用决策模型判断断言是否成立。返回 True/False/None（无法判断）"""
    config = config_manager.get_effective_config()
    if not config.decision_base_url:
        return None
    # 构造 OpenAI 客户端，发送判断 prompt
    # 解析回复中的 PASS/FAIL
```

---

## 验证步骤

1. 数据库执行迁移 SQL，确认 `config_type` 字段存在
2. 前端模型配置页面能切换"视觉模型"/"决策模型" tab
3. 保存后数据库中有两条记录（vision + decision）
4. 客户端同步后能收到决策模型配置
5. 断言步骤中，keyword 匹配失败时自动调用决策模型判断
6. 无决策模型配置时，行为与当前一致（保守 FAIL）
