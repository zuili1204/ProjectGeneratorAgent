// === 工作流详情页逻辑 ===

(function () {
  const $ = (id) => document.getElementById(id);

  // 从 URL 获取 workflow_id
  const params = new URLSearchParams(location.search);
  const workflowId = params.get('id');

  if (!workflowId) {
    $('wf-title').textContent = '错误：缺少 workflow_id 参数';
    toast('无效的工作流 ID', 'error');
    throw new Error('missing workflow_id');
  }

  // === 状态 ===
  let ws = null;
  let wsReconnectTimer = null;
  let state = null;
  let files = [];
  let activeFile = null;
  let isFinished = false;
  let logBuffer = [];
  const MAX_LOG_LINES = 500;

  // === 加载工作流状态 ===
  async function loadState() {
    try {
      const data = await API.getWorkflow(workflowId);
      state = data;
      renderHeader();
      renderTimeline();
      // 状态决定是否需要重连 WS
      if (!isFinished && (state.status === 'running' || state.status === 'paused')) {
        ensureWebSocket();
      }
      // 如果有历史日志，渲染到终端
      if (state.logs && state.logs.length) {
        // 只在没有 WS 连接或日志为空时渲染历史日志
        if (logBuffer.length === 0) {
          state.logs.forEach(entry => appendLog(entry));
        }
      }
    } catch (e) {
      toast(`加载失败: ${e.message}`, 'error');
      console.error(e);
      $('wf-title').textContent = '加载失败';
    }
  }

  // === 加载文件列表 ===
  async function loadFiles() {
    try {
      const data = await API.listFiles(workflowId);
      files = data.files || [];
      renderFileList();
    } catch (e) {
      console.warn('load files failed:', e);
    }
  }

  // === 渲染：顶部 ===
  function renderHeader() {
    $('wf-title').textContent = state.title || '(无标题)';
    $('wf-id').textContent = state.workflow_id.substring(0, 12) + '...';
    const statusEl = $('wf-status');
    statusEl.className = `status-badge status-${state.status}`;
    statusEl.textContent = statusText(state.status);

    // 检查点横幅
    renderCheckpointBanner();

    // 工作流结束
    if (state.status === 'completed' || state.status === 'failed') {
      isFinished = true;
      if (state.status === 'completed') {
        toast('工作流已完成', 'success');
      } else {
        toast('工作流失败', 'error');
      }
    }
  }

  // === 渲染：时间轴 ===
  function renderTimeline() {
    const container = $('timeline');
    if (!state.steps || !state.steps.length) {
      container.innerHTML = '<div class="empty-state" style="padding: 20px;"><div class="empty-state-text">无步骤</div></div>';
      return;
    }
    container.innerHTML = state.steps.map(s => `
      <div class="timeline-step status-${escapeHtml(s.status)}">
        <div class="step-icon"></div>
        <div class="timeline-step-header">
          <div>
            <div class="timeline-step-name">${escapeHtml(s.display_name || s.skill_name)}</div>
            <div class="timeline-step-skill">${escapeHtml(s.skill_name)}</div>
          </div>
          <span class="timeline-step-status">${stepStatusText(s.status)}</span>
        </div>
        ${s.error_message ? `<div class="text-sm" style="color: var(--danger); margin-top: 4px; word-break: break-word; font-size: 11px;">${escapeHtml(s.error_message.substring(0, 100))}</div>` : ''}
      </div>
    `).join('');
  }

  // === 渲染：文件列表（右下） ===
  function renderFileList() {
    const container = $('file-list');
    $('file-count').textContent = files.length;
    if (!files.length) {
      container.innerHTML = '<div class="empty-state" style="padding: 20px;"><div class="empty-state-text">暂无文件</div></div>';
      return;
    }
    container.innerHTML = files.map(f => `
      <div class="file-item ${activeFile === f.path ? 'active' : ''}" data-path="${escapeHtml(f.path)}">
        <span class="file-item-name">${escapeHtml(f.path)}</span>
        <span class="file-item-size">${formatSize(f.size)}</span>
      </div>
    `).join('');
    container.querySelectorAll('.file-item').forEach(el => {
      el.addEventListener('click', () => {
        const path = el.getAttribute('data-path');
        loadFileContent(path);
      });
    });
  }

  // === 加载并显示文件内容 ===
  async function loadFileContent(path) {
    activeFile = path;
    renderFileList();
    $('active-file-name').textContent = path;
    $('active-file-size').textContent = '';
    const contentEl = $('output-content');
    contentEl.innerHTML = '<div class="output-empty"><div>加载中...</div></div>';

    try {
      const data = await API.readFile(workflowId, path);
      const content = data.content || '';
      $('active-file-size').textContent = formatSize(data.size || content.length);

      // 判断渲染方式
      if (path.endsWith('.md')) {
        contentEl.innerHTML = `<div class="file-content markdown">${renderMarkdown(content)}</div>`;
      } else if (path.endsWith('.json')) {
        try {
          const obj = JSON.parse(content);
          contentEl.innerHTML = `<div class="file-content">${escapeHtml(JSON.stringify(obj, null, 2))}</div>`;
        } catch (e) {
          contentEl.innerHTML = `<div class="file-content">${escapeHtml(content)}</div>`;
        }
      } else {
        contentEl.innerHTML = `<div class="file-content">${escapeHtml(content)}</div>`;
      }
    } catch (e) {
      contentEl.innerHTML = `<div class="output-empty"><div style="color: var(--danger);">加载失败: ${escapeHtml(e.message)}</div></div>`;
    }
  }

  // === 渲染：检查点横幅 ===
  function renderCheckpointBanner() {
    const container = $('checkpoint-banner-container');
    const waiting = (state.steps || []).find(s => s.status === 'waiting_checkpoint');
    if (!waiting) {
      container.innerHTML = '';
      return;
    }
    container.innerHTML = `
      <div class="checkpoint-banner">
        <div>
          <strong>⏸ 等待检查点确认：</strong>
          ${escapeHtml(waiting.display_name || waiting.skill_name)} 已完成，请审核产出后选择通过或打回。
        </div>
        <div class="actions">
          <button class="btn btn-success btn-sm" id="cp-approve-btn">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>
            通过
          </button>
          <button class="btn btn-danger btn-sm" id="cp-reject-btn">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
            打回
          </button>
        </div>
      </div>`;
    $('cp-approve-btn').addEventListener('click', () => showCheckpointModal(true));
    $('cp-reject-btn').addEventListener('click', () => showCheckpointModal(false));
  }

  // === 检查点弹窗 ===
  function showCheckpointModal(approved) {
    const title = approved ? '通过检查点' : '打回修改';
    const placeholder = approved
      ? '可选：给模型一些反馈（如「设计可以，但要增加 Redis 缓存」）'
      : '必填：说明哪里需要修改';
    const btnClass = approved ? 'btn-success' : 'btn-danger';
    const btnText = approved ? '确认通过' : '确认打回';

    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
      <div class="modal">
        <div class="modal-header">${title}</div>
        <div class="modal-body">
          <div class="form-group">
            <label class="form-label">反馈内容</label>
            <textarea class="form-textarea" id="cp-feedback" rows="4" placeholder="${escapeHtml(placeholder)}"></textarea>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-ghost btn-sm" id="cp-cancel">取消</button>
          <button class="btn ${btnClass} btn-sm" id="cp-confirm" ${!approved ? 'data-require-feedback="1"' : ''}>${btnText}</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);

    const close = () => overlay.remove();
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    $('cp-cancel').addEventListener('click', close);

    $('cp-confirm').addEventListener('click', async () => {
      const feedback = $('cp-feedback').value.trim();
      if (!approved && !feedback) {
        toast('打回必须填写反馈', 'warning');
        return;
      }
      const btn = $('cp-confirm');
      btn.disabled = true;
      btn.textContent = '提交中...';
      try {
        await API.submitCheckpoint(workflowId, {
          approved,
          feedback,
          run: approved,  // 通过则自动恢复
        });
        toast(approved ? '已通过，工作流恢复中' : '已打回', 'success');
        close();
        // 立即刷新状态
        setTimeout(loadState, 500);
      } catch (e) {
        toast(`提交失败: ${e.message}`, 'error');
        btn.disabled = false;
        btn.textContent = btnText;
      }
    });

    setTimeout(() => $('cp-feedback').focus(), 100);
  }

  // === WebSocket ===
  function ensureWebSocket() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
    if (isFinished) return;

    try {
      ws = new WebSocket(API.wsUrl(workflowId));
    } catch (e) {
      console.warn('WebSocket connect failed:', e);
      scheduleReconnect();
      return;
    }

    setWsStatus('connecting');

    ws.onopen = () => {
      setWsStatus('connected');
    };

    ws.onmessage = (event) => {
      let data;
      try { data = JSON.parse(event.data); } catch (e) { return; }
      handleWsEvent(data);
    };

    ws.onerror = (e) => {
      console.warn('WebSocket error:', e);
      setWsStatus('error');
    };

    ws.onclose = () => {
      setWsStatus('disconnected');
      if (!isFinished) scheduleReconnect();
    };
  }

  function scheduleReconnect() {
    if (wsReconnectTimer) return;
    wsReconnectTimer = setTimeout(() => {
      wsReconnectTimer = null;
      if (!isFinished) ensureWebSocket();
    }, 3000);
  }

  function setWsStatus(s) {
    const indicator = $('ws-indicator');
    const text = $('ws-status');
    const map = {
      connected: { color: 'var(--terminal-green)', text: '已连接' },
      connecting: { color: 'var(--terminal-yellow)', text: '连接中' },
      disconnected: { color: 'var(--fg-subtle)', text: '已断开' },
      error: { color: 'var(--terminal-red)', text: '错误' },
    };
    const cfg = map[s] || map.disconnected;
    indicator.style.background = cfg.color;
    text.textContent = cfg.text;
  }

  function handleWsEvent(event) {
    const etype = event.event;
    if (etype === 'snapshot') {
      state = event.state;
      renderHeader();
      renderTimeline();
      loadFiles();
    } else if (etype === 'log') {
      appendLog(event);
      // 关键日志触发状态刷新
      const msg = event.message || '';
      if (msg.includes('步骤完成') || msg.includes('步骤失败') ||
          msg.includes('工作流执行完成') || msg.includes('工作流失败') ||
          msg.includes('等待检查点')) {
        loadState();
        loadFiles();
      }
    } else if (etype === 'checkpoint') {
      loadState();
    } else if (etype === 'finished') {
      isFinished = true;
      setWsStatus('disconnected');
      toast('工作流已完成', 'success');
      loadState();
      loadFiles();
    } else if (etype === 'failed') {
      isFinished = true;
      setWsStatus('disconnected');
      toast('工作流失败', 'error');
      loadState();
      loadFiles();
    } else if (etype === 'heartbeat') {
      // ignore
    } else if (etype === 'error') {
      toast(`服务器错误: ${event.message || ''}`, 'error');
    }
  }

  // === 追加日志到终端 ===
  function appendLog(entry) {
    // entry: {timestamp, step, level, message}
    const ts = (entry.timestamp || '').substring(11, 19);  // HH:MM:SS
    const step = entry.step || '';
    const level = entry.level || 'info';
    const message = entry.message || '';

    // LLM 调用识别：消息含「LLM」「调用」「tool_call」等关键词 → 用青色
    const isLlm = /LLM|llm|调用.*模型|tool_call|function_call/i.test(message) ||
                  /llm/i.test(level);

    const line = document.createElement('div');
    line.className = `log-line level-${level}${isLlm ? ' level-llm' : ''}`;
    line.innerHTML = `
      <span class="log-time">${escapeHtml(ts)}</span>
      <span class="log-step">${escapeHtml(step)}</span>
      <span class="log-message">${escapeHtml(message)}</span>
    `;
    const body = $('terminal-body');
    body.appendChild(line);
    logBuffer.push(line);
    // 限制日志条数
    if (logBuffer.length > MAX_LOG_LINES) {
      const old = logBuffer.shift();
      if (old && old.parentNode) old.parentNode.removeChild(old);
    }
    // 自动滚动到底部
    body.scrollTop = body.scrollHeight;
  }

  // === 初始化 ===
  document.addEventListener('DOMContentLoaded', () => {
    $('refresh-btn').addEventListener('click', () => {
      loadState();
      loadFiles();
    });

    loadState();
    loadFiles();
    ensureWebSocket();
  });

  // 页面卸载时关闭 WS
  window.addEventListener('beforeunload', () => {
    if (ws) {
      ws.onclose = null;
      ws.close();
    }
  });
})();
