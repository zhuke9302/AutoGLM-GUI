# 计划：根据终端类型调整 message/thinking 取值优先级

## 概述

在执行详情的事件时间线展示中，当终端类型为 PC 时，优先取 `data.thinking`（为空则取 `data.message`）；当终端类型为 APP 时，保持当前逻辑（优先 `data.message`，其次 `data.thinking`）。

## 当前状态分析

### 涉及的两个组件

| 组件 | 文件 | 修改位置 | terminalType 来源 |
|---|---|---|---|
| RunDetailDialog | `frontend/src/views/run/modules/RunDetailDialog.vue` 第 113 行 | `getPayloadContent` 函数 | `props.run.terminalType`（已包含，来自 runStore.mapRun 第 40 行） |
| RunDetailContent | `frontend/src/components/common/RunDetailContent.vue` 第 54 行 | `getPayloadContent` 函数 | `props.runInfo.terminalType`（**当前未映射**，需补充） |

### terminalType 取值

后端返回值为 `'PC'` 或 `'APP'`（见 RunRecordView.vue 第 307 行的判断逻辑）。

### RunDetailContent 的 runInfo 数据流

`RunDetailContent` 被 2 个父组件使用，各有一个 `mapRunInfo` 函数：
1. `frontend/src/views/evidence/EvidenceCenterView.vue` 第 94-107 行
2. `frontend/src/views/incident/IncidentClosureView.vue` 第 154-167 行

两个 `mapRunInfo` 都未映射 `terminalType` 字段，需要补充。`raw` 来自 `getRunDetail` API 返回的 `res.data.run`，包含 `terminalType` 字段。

### RunDetailDialog 的 run 数据流

`props.run` 来自 `runStore.runs`（由 `mapRun` 函数映射，第 40 行已包含 `terminalType: raw.terminalType || ""`），可直接使用。

## 修改方案

### 修改 1：RunDetailDialog.vue — getPayloadContent 中按终端类型取值

**文件**: `g:\workspace\cuc-ikb-ai-xunjian-repository\frontend\src\views\run\modules\RunDetailDialog.vue`
**位置**: 第 112-113 行

```javascript
// 修改前：
// 优先 message，其次 thinking
const msg = data.message || data.thinking || ''

// 修改后：
// PC 端优先 thinking，APP 端优先 message
const isPC = props.run?.terminalType === 'PC'
const msg = isPC
  ? (data.thinking || data.message || '')
  : (data.message || data.thinking || '')
```

### 修改 2：RunDetailContent.vue — getPayloadContent 中按终端类型取值

**文件**: `g:\workspace\cuc-ikb-ai-xunjian-repository\frontend\src\components\common\RunDetailContent.vue`
**位置**: 第 53-54 行

```javascript
// 修改前：
// 优先 message，其次 thinking
const msg = data.message || data.thinking || ''

// 修改后：
// PC 端优先 thinking，APP 端优先 message
const isPC = props.runInfo?.terminalType === 'PC'
const msg = isPC
  ? (data.thinking || data.message || '')
  : (data.message || data.thinking || '')
```

### 修改 3：EvidenceCenterView.vue — mapRunInfo 补充 terminalType

**文件**: `g:\workspace\cuc-ikb-ai-xunjian-repository\frontend\src\views\evidence\EvidenceCenterView.vue`
**位置**: 第 94-107 行 `mapRunInfo` 函数

在返回对象中添加 `terminalType: raw.terminalType || ''`。

### 修改 4：IncidentClosureView.vue — mapRunInfo 补充 terminalType

**文件**: `g:\workspace\cuc-ikb-ai-xunjian-repository\frontend\src\views\incident\IncidentClosureView.vue`
**位置**: 第 154-167 行 `mapRunInfo` 函数

在返回对象中添加 `terminalType: raw.terminalType || ''`。

## 假设与决策

1. **terminalType 判断值**：后端返回 `'PC'` 表示 PC Web，`'APP'` 表示 App（基于 RunRecordView.vue 第 307 行的现有逻辑）
2. **仅修改 msg 变量**：`data.message` 在其他 case 分支（如 `error`、`user_message`、`done`）中的使用不受影响，只调整 `msg` 变量的取值优先级
3. **runInfo 为 null 时安全降级**：`props.runInfo?.terminalType` 使用可选链，当 runInfo 为 null 时 `isPC` 为 false，走 APP 逻辑（当前默认行为）

## 验证步骤

1. 前端 lint：`cd frontend && pnpm lint`（或 `pnpm run lint`）
2. 前端格式检查：`cd frontend && pnpm format:check`
