/**
 * 轻量级文件日志模块 - 将 midscene-service 日志写入本地文件。
 *
 * 与 Python loguru 日志体系保持一致：
 *   - 日志文件: logs/midscene-service_{date}.log
 *   - 格式: YYYY-MM-DD HH:mm:ss.SSS | LEVEL | [TAG] - message
 *   - 同时输出到控制台和文件
 */

const fs = require('fs');
const path = require('path');

// 日志目录：优先使用环境变量（Electron userData/logs），回退到相对路径
const LOGS_DIR = process.env.MIDSCENE_LOGS_DIR
  ? path.resolve(process.env.MIDSCENE_LOGS_DIR)
  : path.resolve(__dirname, '..', 'logs');

/** 确保 logs 目录存在，不存在则创建 */
ensureLogDir();
function ensureLogDir() {
  if (!fs.existsSync(LOGS_DIR)) {
    fs.mkdirSync(LOGS_DIR, { recursive: true });
  }
}

/** 获取当天日志文件路径 */
function getLogPath() {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, '0');
  const d = String(now.getDate()).padStart(2, '0');
  return path.join(LOGS_DIR, `midscene-service_${y}-${m}-${d}.log`);
}

/** 格式化时间戳 */
function timestamp() {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, '0');
  const d = String(now.getDate()).padStart(2, '0');
  const h = String(now.getHours()).padStart(2, '0');
  const min = String(now.getMinutes()).padStart(2, '0');
  const s = String(now.getSeconds()).padStart(2, '0');
  const ms = String(now.getMilliseconds()).padStart(3, '0');
  return `${y}-${m}-${d} ${h}:${min}:${s}.${ms}`;
}

const logPath = getLogPath();
console.log(`[logger] 日志目录: ${LOGS_DIR}`);
console.log(`[logger] 日志文件: ${logPath}`);

// 启动时写入一条标记
try {
  fs.appendFileSync(logPath, `=== midscene-service started at ${timestamp()} ===\n`, 'utf-8');
} catch (err) {
  console.error(`[logger] 初始化写入失败: ${err.message}`);
}

/**
 * 写入一条日志。同时输出到控制台和文件。
 * @param {'INFO'|'WARN'|'ERROR'|'DEBUG'} level
 * @param {string} tag
 * @param {string} msg
 */
function writeLog(level, tag, msg) {
  const line = `${timestamp()} | ${level.padEnd(5)} | [${tag}] - ${msg}`;

  // 控制台输出
  switch (level) {
    case 'ERROR':
      console.error(line);
      break;
    case 'WARN':
      console.warn(line);
      break;
    default:
      console.log(line);
  }

  // 文件输出 - 每条日志立即同步写入
  try {
    fs.appendFileSync(getLogPath(), line + '\n', 'utf-8');
  } catch (err) {
    console.error(`[logger] 文件写入失败: ${err.message}`);
  }
}

const serviceLogger = {
  info(tag, msg) { writeLog('INFO', tag, msg); },
  warn(tag, msg) { writeLog('WARN', tag, msg); },
  error(tag, msg) { writeLog('ERROR', tag, msg); },
  debug(tag, msg) { writeLog('DEBUG', tag, msg); },
  close() { /* no-op */ },
};

module.exports = { serviceLogger };
