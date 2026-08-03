/**
 * BrowserExecutor - Playwright + @midscene/web 执行器
 *
 * 封装浏览器生命周期和巡检任务执行，将 Midscene 的进度事件
 * 转换为 AutoGLM-GUI AsyncAgent 协议的 SSE 事件格式。
 */

const { chromium } = require('playwright');
const { PlaywrightAgent } = require('@midscene/web/playwright');
const { serviceLogger } = require('./logger');

class BrowserExecutor {
  constructor() {
    /** @type {import('playwright').Browser | null} */
    this.browser = null;
    /** @type {import('playwright').Page | null} */
    this.page = null;
    /** @type {import('@midscene/web/playwright').PlaywrightAgent | null} */
    this.agent = null;
    /** @type {string | null} */
    this.currentTaskId = null;
    /** @type {boolean} */
    this.aborted = false;
    /** @type {AbortController | null} */
    this._abortController = null;
  }

  /**
   * 启动浏览器实例。
   * 优先使用系统 Chrome（channel: 'chrome'），失败则回退到 Playwright 内置 Chromium。
   */
  async launch() {
    if (this.browser) return;

    serviceLogger.info('BrowserExecutor', '正在启动浏览器…');

    try {
      this.browser = await chromium.launch({
        channel: 'chrome',
        headless: true,
      });
      serviceLogger.info('BrowserExecutor', '使用系统 Chrome 启动成功');
    } catch (err) {
      serviceLogger.warn('BrowserExecutor', `系统 Chrome 启动失败, 回退 Playwright Chromium: ${err.message}`);
      try {
        this.browser = await chromium.launch({ headless: true });
        serviceLogger.info('BrowserExecutor', 'Playwright Chromium 启动成功');
      } catch (err2) {
        serviceLogger.error('BrowserExecutor', `浏览器启动失败: ${err2.message}`);
        throw err2;
      }
    }

    this.page = await this.browser.newPage();
    serviceLogger.info('BrowserExecutor', '新页面已创建');
  }

  /**
   * 导航到指定 URL。
   */
  async navigate(url) {
    this._assertReady();
    serviceLogger.info('BrowserExecutor', `导航到: ${url}`);
    try {
      await this.page.goto(url, { waitUntil: 'networkidle', timeout: 30000 });
      const currentUrl = this.page.url();
      serviceLogger.info('BrowserExecutor', `导航完成, 当前 URL: ${currentUrl}`);
    } catch (err) {
      serviceLogger.error('BrowserExecutor', `导航失败: ${err.message}`);
      throw err;
    }
  }

  /**
   * 登录环境：导航到 URL 后，使用 AI 智能填写账号密码并提交登录。
   *
   * @param {string} url - 目标环境 URL
   * @param {string} account - 登录账号
   * @param {string} password - 登录密码
   * @returns {Promise<{loginUrl: string}>} 登录后的页面 URL
   */
  async login(url, account, password) {
    this._assertReady();
    serviceLogger.info('BrowserExecutor', `登录环境: url=${url}, account=${account}`);

    // 先导航到登录页面
    await this.navigate(url);

    // 使用 AI 智能登录：让 Midscene Agent 填写账号密码并提交
    const loginPrompt = `请执行登录操作：在登录页面中，找到用户名/账号输入框，输入"${account}"；找到密码输入框，输入"${password}"；然后点击登录/提交按钮完成登录。如果页面上有验证码或其他需要人工操作的步骤，请跳过。`;

    try {
      const agent = new PlaywrightAgent(this.page, {
        modelName: process.env.MIDSCENE_MODEL_NAME,
        modelApiKey: process.env.MIDSCENE_API_KEY,
        modelBaseUrl: process.env.MIDSCENE_BASE_URL,
      });

      await agent.aiAction(loginPrompt);

      // 等待页面跳转完成
      await this.page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {
        serviceLogger.warn('BrowserExecutor', '登录后等待 networkidle 超时，继续执行');
      });

      const currentUrl = this.page.url();
      serviceLogger.info('BrowserExecutor', `登录完成, 当前 URL: ${currentUrl}`);
      return { loginUrl: currentUrl };
    } catch (err) {
      serviceLogger.error('BrowserExecutor', `登录失败: ${err.message}`);
      throw err;
    }
  }

  /**
   * 检测并提取断言 prompt。
   *
   * task_manager 会将断言步骤的 prompt 格式化为：
   *   "断言" + step_name + _ASSERTION_SUFFIX
   * 其中 _ASSERTION_SUFFIX 包含 "【重要】" 标记，要求模型输出 RESULT: PASS/FAIL。
   *
   * 此方法提取纯断言内容，供 aiAssert 使用。
   *
   * @param {string} prompt - 原始 prompt
   * @returns {string|null} - 纯断言内容；非断言 prompt 返回 null
   */
  _extractAssertionPrompt(prompt) {
    serviceLogger.info('BrowserExecutor', `_extractAssertionPrompt: prompt="${prompt ? prompt.substring(0, 80) : '(empty)'}", startsWith断言=${prompt ? prompt.startsWith('断言') : false}`);
    if (!prompt || !prompt.startsWith('断言')) return null;
    // 去掉 "断言" 前缀
    let content = prompt.slice(2);
    // 去掉 _ASSERTION_SUFFIX（从 "【重要】" 开始的部分）
    const suffixIdx = content.indexOf('【重要】');
    if (suffixIdx !== -1) {
      content = content.slice(0, suffixIdx);
    }
    return content.trim();
  }

  /**
   * 执行断言任务，使用 aiAssert 代替 aiAct。
   *
   * aiAssert 返回 boolean，映射为：
   * - true  → done 事件，message 含 "PASS"，success=true
   * - false → done 事件，message 含 "FAIL"，success=false（业务失败，非运行错误）
   *
   * @param {string} url - 目标页面 URL
   * @param {string} assertionContent - 纯断言内容（已去除前缀和 suffix）
   * @param {(event: object) => void} onEvent - SSE 事件回调
   * @param {number} stepCount - 当前步骤数
   */
  async _executeAssertion(url, assertionContent, onEvent, stepCount) {
    onEvent({
      type: 'thinking',
      data: { chunk: `正在执行断言: ${assertionContent}` },
    });

    try {
      // keepRawResponse: true 让 aiAssert 返回 {pass, thought, message} 对象，
      // 而不是在断言失败时抛异常。断言失败属于业务异常，不是运行错误。
      const assertResult = await this.agent.aiAssert(assertionContent, undefined, {
        abortSignal: this._abortController.signal,
        keepRawResponse: true,
      });

      if (this.aborted) {
        onEvent({ type: 'cancelled', data: { message: '任务已取消' } });
        return;
      }

      const pass = assertResult.pass;
      const thought = assertResult.thought || '';

      // 截图
      let screenshotB64 = null;
      try {
        const buf = await this.page.screenshot({ type: 'png' });
        screenshotB64 = buf.toString('base64');
      } catch (e) {
        serviceLogger.warn('BrowserExecutor', `断言截图失败: ${e.message}`);
      }

      // 发送 step 事件
      const stepData = {
        step: stepCount,
        thinking: thought ? `断言: ${assertionContent}\n${thought}` : `断言: ${assertionContent}`,
        action: { _metadata: 'Midscene', type: 'aiAssert', description: assertionContent },
        success: true,
        message: pass ? 'PASS' : 'FAIL',
      };
      if (screenshotB64) {
        stepData.screenshot = screenshotB64;
      }
      onEvent({ type: 'step', data: stepData });

      // 发送 done 事件
      if (pass) {
        onEvent({
          type: 'done',
          data: {
            message: 'RESULT: PASS',
            steps: stepCount,
            success: true,
          },
        });
      } else {
        onEvent({
          type: 'done',
          data: {
            message: 'RESULT: FAIL',
            steps: stepCount,
            success: false,
          },
        });
      }
    } catch (err) {
      serviceLogger.warn('BrowserExecutor', `断言异常: ${err.message}`);
      const msg = err.message || '';
      if (this.aborted) {
        onEvent({ type: 'cancelled', data: { message: '任务已取消' } });
      } else {
        // 断言执行异常属于运行错误，发送 error 事件
        onEvent({
          type: 'error',
          data: { message: `断言执行异常: ${msg}` },
        });
      }
    }
  }

  /**
   * 执行巡检任务，通过 onEvent 回调发送 SSE 兼容事件。
   *
   * 事件类型:
   * - thinking:  {"type":"thinking","data":{"chunk":"..."}}
   * - step:      {"type":"step","data":{"step":1,"thinking":"...","action":{...}}}
   * - done:      {"type":"done","data":{"message":"...","success":true}}
   * - error:     {"type":"error","data":{"message":"..."}}
   * - cancelled: {"type":"cancelled","data":{"message":"..."}}
   *
   * @param {string} url - 目标页面 URL
   * @param {string} prompt - 巡检指令（自然语言）
   * @param {string} [taskId] - 任务 ID
   * @param {(event: object) => void} onEvent - SSE 事件回调
   */
  async execute(url, prompt, taskId, onEvent, skipNavigate = false) {
    this.currentTaskId = taskId || null;
    this.aborted = false;
    this._abortController = new AbortController();

    let stepCount = 0;

    // --- 断言步骤：在导航前检测，使用 aiAssert 代替 aiAct ---
    const assertionContent = this._extractAssertionPrompt(prompt);
    if (assertionContent) {
      serviceLogger.info('BrowserExecutor', `检测到断言 prompt，走 aiAssert 分支: "${assertionContent.substring(0, 60)}"`);
      // 断言步骤不需要重新导航，直接在当前页面执行
      this.agent = new PlaywrightAgent(this.page, {
        generateReport: false,
        autoPrintReportMsg: false,
      });
      stepCount++;
      await this._executeAssertion(url, assertionContent, onEvent, stepCount);
      return;
    }

    try {
      // --- 导航（skipNavigate=true 时跳过，避免覆盖已登录的页面） ---
      serviceLogger.info('BrowserExecutor', `开始执行任务, URL: ${url}, skipNavigate: ${skipNavigate}, Prompt: ${prompt}`);

      if (skipNavigate) {
        serviceLogger.info('BrowserExecutor', `跳过导航，使用当前页面: ${this.page.url()}`);
        onEvent({
          type: 'thinking',
          data: { chunk: `在当前页面继续执行任务` },
        });
      } else {
        onEvent({
          type: 'thinking',
          data: { chunk: `正在导航到 ${url} …` },
        });
        await this.page.goto(url, { waitUntil: 'networkidle', timeout: 30000 });
        const currentUrl = this.page.url();
        serviceLogger.info('BrowserExecutor', `导航完成, 当前页面: ${currentUrl}`);
      }

      // --- 创建 Agent ---
      this.agent = new PlaywrightAgent(this.page, {
        generateReport: false,
        autoPrintReportMsg: false,
      });

      // --- 当前步骤截图队列 ---
      let pendingStep = null;  // 待发送的 step 数据

      // --- 注册进度监听，将 Midscene 事件转为 SSE 事件 ---
      const dispose = this.agent.addProgressListener(async (event) => {
        if (event.scope !== 'aiAct') return;

        try {
        switch (event.phase) {
          case 'start':
            onEvent({
              type: 'thinking',
              data: { chunk: `开始执行任务: ${event.data?.prompt || prompt}` },
            });
            break;

          case 'plan_thinking':
            if (event.data?.thought) {
              onEvent({
                type: 'thinking',
                data: { chunk: event.data.thought },
              });
            }
            break;

          case 'plan_planned': {
            stepCount++;
            const action = event.data?.action || {};
            const actionDisplay = {
              _metadata: 'Midscene',
              type: action.name || 'unknown',
            };
            if (action.target) actionDisplay.description = action.target;
            if (action.param) actionDisplay.param = action.param;
            if (action.point) actionDisplay.point = action.point;

            // 暂存 step 数据，等截图完成后一起发送
            pendingStep = {
              step: stepCount,
              thinking: event.data?.thought || '',
              action: actionDisplay,
              success: true,
              message: event.data?.log || '',
            };
            break;
          }

          case 'action_running':
            onEvent({
              type: 'thinking',
              data: {
                chunk: event.data?.log
                  ? `正在执行: ${event.data.log}`
                  : '正在执行操作…',
              },
            });
            break;

          case 'action_done':
            // 动作执行完成，截图并发送完整 step 事件
            if (pendingStep) {
              try {
                const buf = await this.page.screenshot({ type: 'png' });
                const screenshotB64 = buf.toString('base64');
                serviceLogger.info('BrowserExecutor', `步骤 ${pendingStep.step} 截图已完成`);
                onEvent({
                  type: 'step',
                  data: {
                    ...pendingStep,
                    screenshot: screenshotB64,
                  },
                });
              } catch (e) {
                serviceLogger.warn('BrowserExecutor', `截图失败: ${e.message}`);
                // 无截图也要发送 step 事件
                onEvent({ type: 'step', data: pendingStep });
              }
              pendingStep = null;
            }
            break;

          case 'action_failed':
            onEvent({
              type: 'thinking',
              data: {
                chunk: `操作执行失败: ${event.data?.error || '未知错误'}`,
              },
            });
            break;

          case 'plan_failed':
            onEvent({
              type: 'thinking',
              data: {
                chunk: `规划失败: ${event.data?.error || '未知错误'}`,
              },
            });
            break;

          default:
            break;
        }
        } catch (_e) {
          // ignore progress listener errors
        }
      });

      // --- 执行巡检 ---
      onEvent({
        type: 'thinking',
        data: { chunk: `开始执行巡检: ${prompt}` },
      });

      const result = await this.agent.aiAct(prompt, {
        abortSignal: this._abortController.signal,
      });

      // 清理进度监听
      if (typeof dispose === 'function') dispose();

      // 发送完成事件
      if (this.aborted) {
        onEvent({ type: 'cancelled', data: { message: '任务已取消' } });
      } else {
        onEvent({
          type: 'done',
          data: {
            message: result || '巡检任务执行完毕',
            steps: stepCount,
            success: true,
          },
        });
      }
    } catch (err) {
      serviceLogger.warn('BrowserExecutor', `任务异常: ${err.message}`);
      const msg = err.message || '';
      try {
        if (this.aborted) {
          onEvent({ type: 'cancelled', data: { message: '任务已取消' } });
        } else if (msg.startsWith('Task failed:')) {
          // 断言失败属于任务结果，非系统错误
          onEvent({
            type: 'done',
            data: {
              message: msg,
              steps: stepCount,
              success: false,
            },
          });
        } else {
          onEvent({
            type: 'error',
            data: { message: msg || '巡检执行异常' },
          });
        }
      } catch (_sendErr) {
        // SSE 连接已断开，忽略发送失败
      }
    } finally {
      // 清理 Agent（不生成报告文件）
      if (this.agent) {
        try {
          await this.agent.destroy();
        } catch {
          // ignore cleanup errors
        }
        this.agent = null;
      }
      this._abortController = null;
    }
  }

  /**
   * 获取当前页面截图。
   * @returns {{ screenshot: string, width: number, height: number }}
   */
  async screenshot() {
    this._assertReady();
    const buffer = await this.page.screenshot();
    const viewport = this.page.viewportSize();
    return {
      screenshot: buffer.toString('base64'),
      width: viewport?.width || 1920,
      height: viewport?.height || 1080,
    };
  }

  /**
   * 点击页面坐标。
   */
  async tap(x, y) {
    this._assertReady();
    await this.page.mouse.click(x, y);
  }

  /**
   * 在当前焦点位置输入文本。
   */
  async typeText(text) {
    this._assertReady();
    await this.page.keyboard.type(text);
  }

  /**
   * 取消正在执行的任务。
   */
  cancel() {
    this.aborted = true;
    if (this._abortController) {
      this._abortController.abort();
    }
  }

  /**
   * 关闭浏览器，释放所有资源。
   */
  async close() {
    if (this.agent) {
      try {
        await this.agent.destroy();
      } catch {
        // ignore
      }
      this.agent = null;
    }
    if (this.browser) {
      await this.browser.close();
      this.browser = null;
      this.page = null;
    }
    this.currentTaskId = null;
    this.aborted = false;
  }

  /** @private */
  _assertReady() {
    if (!this.browser || !this.page) {
      throw new Error('浏览器未启动，请先调用 launch()');
    }
  }
}

module.exports = { BrowserExecutor };
