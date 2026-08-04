# Tasks

- [x] Task 1: 后端数据库表和Entity新增PC视觉模型字段
  - [x] SubTask 1.1: `schema.sql` 中 `patrol_model_configs` 表新增 `pc_base_url`、`pc_model_name`、`pc_api_key` 三列，并添加迁移 ALTER 语句
  - [x] SubTask 1.2: `PatrolModelConfig.java` Entity 新增 `pcBaseUrl`、`pcModelName`、`pcApiKey` 三个字段及 getter/setter

- [x] Task 2: 后端同步接口新增PC视觉模型字段
  - [x] SubTask 2.1: `ClientSyncController.java` 的 `ConfigSyncResponse` 内嵌类新增 `pcBaseUrl`、`pcModelName`、`pcApiKey` 字段
  - [x] SubTask 2.2: `ClientSyncController.java` 的 `syncConfig` 方法返回值中填充 PC 视觉模型字段

- [x] Task 3: 前端表单弹窗新增PC视觉模型Tab
  - [x] SubTask 3.1: `ModelConfigFormDialog.vue` 新增 `pcVisionForm` reactive 对象（pcModelName/pcBaseUrl/pcApiKey）
  - [x] SubTask 3.2: 在 el-tabs 中新增 "PC视觉模型" Tab Pane（位于 APP视觉模型 和 决策模型 之间）
  - [x] SubTask 3.3: 将现有 "视觉模型" Tab 标签改为 "APP视觉模型"
  - [x] SubTask 3.4: `handleSubmit` 中将 PC 视觉模型字段合并到提交 payload（pcBaseUrl/pcModelName/pcApiKey）
  - [x] SubTask 3.5: `openEditDialog`/`fillFromEdit`/`resetForm` 中处理 PC 视觉模型字段

- [x] Task 4: 前端列表页和Store适配
  - [x] SubTask 4.1: `ModelConfigView.vue` 表格新增 "PC视觉模型" 列
  - [x] SubTask 4.2: `stores/modelConfig.js` 的 `batchSave` 方法合并 PC 视觉模型字段

- [x] Task 5: 客户端同步schema和配置应用逻辑
  - [x] SubTask 5.1: `sync/schemas.py` 的 `ServerConfigResponse` 新增 `pc_base_url`、`pc_model_name`、`pc_api_key` 字段
  - [x] SubTask 5.2: `sync/sync_pull.py` 的 `_apply_server_config` 方法将 PC 视觉模型字段写入 server_values

- [x] Task 6: 客户端web-browser agent初始化使用PC视觉模型配置
  - [x] SubTask 6.1: `phone_agent_manager.py` 的 `_auto_initialize_agent_unsafe` 方法中，当 agent_type 为 midscene-web 时，优先使用 pc_base_url/pc_model_name/pc_api_key 构建 ModelConfig，为空时降级使用 APP 配置

- [x] Task 7: MidsceneWebAgent向midscene-service推送模型配置
  - [x] SubTask 7.1: `agents/midscene_web/async_agent.py` 的 `_stream_impl` 方法中，在发送 `/navigate` 请求前先调用 `POST /config` 推送 aiConfig（包含 MIDSCENE_MODEL_BASE_URL/MIDSCENE_MODEL_NAME/MIDSCENE_MODEL_API_KEY）
  - [x] SubTask 7.2: 当 model_config 的 base_url 或 model_name 为空时跳过 `/config` 推送

# Task Dependencies
- Task 2 depends on Task 1
- Task 3 depends on Task 1 (字段定义)
- Task 4 depends on Task 3
- Task 5 depends on Task 2
- Task 6 depends on Task 5
- Task 7 depends on Task 6
