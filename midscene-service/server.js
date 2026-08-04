/**
 * Midscene Web Patrol Service
 *
 * Express HTTP 微服务，通过 REST API 接收巡检指令，
 * 使用 Playwright + @midscene/web SDK 驱动浏览器执行巡检。
 *
 * 接口:
 *   GET  /health     - 健康检查
 *   POST /execute    - 执行巡检任务（SSE 事件流）
 *   POST /cancel     - 取消正在执行的任务
 *   POST /screenshot  - 获取当前页面截图
 *   POST /tap        - 点击坐标
 *   POST /type       - 输入文本
 *   POST /navigate   - 导航到 URL
 */

require('dotenv').config();

const express = require('express');
const { BrowserExecutor } = require('./executor');
const { serviceLogger } = require('./logger');

const app = express();
app.use(express.json());

const PORT = parseInt(process.env.PORT, 10) || 39000;
const startTime = Date.now();

// --- 单例执行器 ---
const executor = new BrowserExecutor();
let browserLaunched = false;

/**
 * 确保浏览器已启动（懒初始化）。
 */
async function ensureBrowser() {
  if (!browserLaunched) {
    serviceLogger.info('server', '懒初始化浏览器…');
    try {
      await executor.launch();
      browserLaunched = true;
      serviceLogger.info('server', '浏览器初始化完成');
    } catch (err) {
      serviceLogger.error('server', `浏览器初始化失败: ${err.message}`);
      throw err;
    }
  }
}

// ------------------------------------------------------------------ /config

app.post('/config', (req, res) => {
  const { aiConfig } = req.body || {};
  if (!aiConfig || typeof aiConfig !== 'object') {
    serviceLogger.warn('server', '/config 缺少 aiConfig 参数');
    return res.status(400).json({ error: '缺少 aiConfig 参数' });
  }

  serviceLogger.info('server', `收到模型配置推送: ${JSON.stringify(Object.keys(aiConfig))}`);

  // 将推送的配置写入 process.env，供 PlaywrightAgent 读取
  for (const [key, value] of Object.entries(aiConfig)) {
    if (typeof value === 'string' && value.trim()) {
      process.env[key] = value;
      serviceLogger.info('server', `设置环境变量: ${key}=${value.substring(0, 20)}...`);
    }
  }

  res.json({ status: 'ok', message: '模型配置已更新' });
});

// ------------------------------------------------------------------ /health

app.get('/health', (_req, res) => {
  res.json({
    status: 'ok',
    version: '1.0.0',
    uptime: Math.floor((Date.now() - startTime) / 1000),
  });
});

// ------------------------------------------------------------------ /execute

app.post('/execute', async (req, res) => {
  const { url, prompt, taskId, skipNavigate } = req.body || {};

  serviceLogger.info('server', `POST /execute: url=${url}, prompt=${prompt}, taskId=${taskId}, skipNavigate=${skipNavigate}`);

  if (!prompt) {
    serviceLogger.warn('server', `缺少参数: prompt=${prompt}`);
    return res.status(400).json({ error: '缺少 prompt 参数' });
  }

  // 设置 SSE 响应头
  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache',
    Connection: 'keep-alive',
    'X-Accel-Buffering': 'no',
  });

  /**
   * 将事件写入 SSE 流。
   * @param {{ type: string, data: object }} event
   */
  const sendEvent = (event) => {
    res.write(`data: ${JSON.stringify(event)}\n\n`);
  };

  try {
    await ensureBrowser();
    await executor.execute(url || 'about:blank', prompt, taskId, sendEvent, !!skipNavigate);
  } catch (err) {
    sendEvent({
      type: 'error',
      data: { message: err.message || '服务内部错误' },
    });
  } finally {
    res.end();
  }
});

// ------------------------------------------------------------------ /cancel

app.post('/cancel', (_req, res) => {
  executor.cancel();
  res.json({ status: 'ok', message: '取消指令已发送' });
});

// ------------------------------------------------------------------ /screenshot

app.post('/screenshot', async (_req, res) => {
  try {
    await ensureBrowser();
    const data = await executor.screenshot();
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ------------------------------------------------------------------ /tap

app.post('/tap', async (req, res) => {
  const { x, y } = req.body || {};
  if (typeof x !== 'number' || typeof y !== 'number') {
    return res.status(400).json({ error: '缺少 x 或 y 参数' });
  }
  try {
    await ensureBrowser();
    await executor.tap(x, y);
    res.json({ status: 'ok' });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ------------------------------------------------------------------ /type

app.post('/type', async (req, res) => {
  const { text } = req.body || {};
  if (typeof text !== 'string') {
    return res.status(400).json({ error: '缺少 text 参数' });
  }
  try {
    await ensureBrowser();
    await executor.typeText(text);
    res.json({ status: 'ok' });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ------------------------------------------------------------------ /navigate

app.post('/navigate', async (req, res) => {
  const { url } = req.body || {};
  serviceLogger.info('server', `POST /navigate: url=${url}`);
  if (!url) {
    serviceLogger.warn('server', '/navigate 缺少 url 参数');
    return res.status(400).json({ error: '缺少 url 参数' });
  }
  try {
    await ensureBrowser();
    await executor.navigate(url);
    serviceLogger.info('server', `/navigate 完成: ${url}`);
    res.json({ status: 'ok' });
  } catch (err) {
    serviceLogger.error('server', `/navigate 失败: ${err.message}`);
    res.status(500).json({ error: err.message });
  }
});

// ------------------------------------------------------------------ /login

app.post('/login', async (req, res) => {
  const { url, account, password } = req.body || {};
  serviceLogger.info('server', `POST /login: url=${url}, account=${account}`);
  if (!url || !account || !password) {
    serviceLogger.warn('server', '/login 缺少参数');
    return res.status(400).json({ error: '缺少 url、account 或 password 参数' });
  }
  try {
    await ensureBrowser();
    const result = await executor.login(url, account, password);
    serviceLogger.info('server', `/login 完成: url=${url}, account=${account}`);
    res.json({ status: 'ok', ...result });
  } catch (err) {
    serviceLogger.error('server', `/login 失败: ${err.message}`);
    res.status(500).json({ error: err.message });
  }
});

// ------------------------------------------------------------------ 启动

app.listen(PORT, () => {
  serviceLogger.info('server', `服务已启动, 监听端口 ${PORT}`);
  serviceLogger.info('server', `健康检查: http://localhost:${PORT}/health`);
});

// 优雅关闭
process.on('SIGINT', async () => {
  serviceLogger.info('server', '正在关闭 (SIGINT)…');
  await executor.close();
  serviceLogger.close();
  process.exit(0);
});

process.on('SIGTERM', async () => {
  serviceLogger.info('server', '正在关闭 (SIGTERM)…');
  await executor.close();
  serviceLogger.close();
  process.exit(0);
});
