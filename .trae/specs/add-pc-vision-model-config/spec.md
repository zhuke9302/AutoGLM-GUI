# PC视觉模型配置 Spec

## Why
当前模型配置只有一套视觉模型参数（base_url/model_name/api_key），同时服务于 APP 和 PC Web 巡检。但 PC Web 使用 midscene-web agent，与 APP 使用的手机 agent 对模型的需求不同，需要独立配置 PC 视觉模型参数。同时 midscene-service 当前使用自身工程配置文件中的模型，需要改为使用从服务端同步过来的 PC 模型配置。

## What Changes
- 数据库表 `patrol_model_configs` 新增 3 个字段：`pc_base_url`、`pc_model_name`、`pc_api_key`
- 后端 Entity、同步接口同步新增 PC 视觉模型字段
- 前端表单弹窗新增 "PC视觉模型" Tab，现有 "视觉模型" Tab 改名为 "APP视觉模型"
- 前端列表页表格新增 PC 视觉模型列
- 客户端同步 schema 和配置应用逻辑新增 PC 视觉模型字段
- 客户端初始化 web-browser agent 时使用 PC 视觉模型配置构建 ModelConfig
- MidsceneWebAgent 在连接 midscene-service 时，通过 `/config` 接口将 PC 模型配置推送到 midscene-service，使其不再依赖工程配置文件

## Impact
- Affected code:
  - 后端: `PatrolModelConfig.java`、`ClientSyncController.java`、`schema.sql`
  - 前端: `ModelConfigFormDialog.vue`、`ModelConfigView.vue`、`stores/modelConfig.js`
  - 客户端: `sync/schemas.py`、`sync/sync_pull.py`、`phone_agent_manager.py`、`agents/midscene_web/async_agent.py`、`agents/factory.py`

## ADDED Requirements

### Requirement: PC视觉模型配置字段
系统 SHALL 在模型配置表中新增 `pc_base_url`、`pc_model_name`、`pc_api_key` 三个字段，用于独立配置 PC Web 巡检的视觉模型参数。

#### Scenario: 新增模型配置时填写PC视觉模型
- **WHEN** 用户在模型配置表单中切换到 "PC视觉模型" Tab
- **THEN** 显示 PC 视觉模型的 base_url、model_name、api_key 三个输入字段
- **AND** 这些字段为可选（非必填），允许只配置 APP 视觉模型

#### Scenario: 客户端同步PC视觉模型配置
- **WHEN** 客户端拉取服务端配置时
- **THEN** 响应中包含 `pc_base_url`、`pc_model_name`、`pc_api_key` 字段
- **AND** 客户端将这些值应用到配置层中

#### Scenario: web-browser设备初始化agent时使用PC视觉模型配置
- **WHEN** 客户端为 web-browser 设备初始化 midscene-web agent
- **THEN** 优先使用 PC 视觉模型配置（pc_base_url/pc_model_name/pc_api_key）构建 ModelConfig
- **AND** 如果 PC 配置为空，降级使用 APP 视觉模型配置（base_url/model_name/api_key）

### Requirement: MidsceneWebAgent向midscene-service推送模型配置
MidsceneWebAgent SHALL 在首次连接 midscene-service 时，通过 `POST /config` 接口将 PC 模型配置（MIDSCENE_MODEL_BASE_URL、MIDSCENE_MODEL_NAME、MIDSCENE_MODEL_API_KEY）推送到 midscene-service，使其使用同步过来的模型信息而非工程配置文件中的模型。

#### Scenario: 首次执行任务前推送模型配置
- **WHEN** MidsceneWebAgent 首次向 midscene-service 发送请求前
- **THEN** 先调用 `POST /config` 接口推送 aiConfig
- **AND** aiConfig 包含 MIDSCENE_MODEL_BASE_URL、MIDSCENE_MODEL_NAME、MIDSCENE_MODEL_API_KEY 三个字段
- **AND** 推送成功后再继续执行导航和任务请求

#### Scenario: 模型配置为空时跳过推送
- **WHEN** PC 模型配置的 base_url 或 model_name 为空
- **THEN** 跳过 `/config` 推送，midscene-service 使用自身工程配置文件中的默认模型

## MODIFIED Requirements

### Requirement: 模型配置表单Tab结构
模型配置表单弹窗 SHALL 包含三个 Tab：
1. "APP视觉模型"（原"视觉模型"改名，字段不变）
2. "PC视觉模型"（新增，含 pc_base_url/pc_model_name/pc_api_key）
3. "决策模型"（保持不变）

### Requirement: 模型配置列表展示
模型配置列表页 SHALL 在表格中展示 APP 视觉模型和 PC 视觉模型的模型名称。

### Requirement: 客户端配置同步响应
`ConfigSyncResponse` SHALL 新增 `pcBaseUrl`、`pcModelName`、`pcApiKey` 三个字段。
