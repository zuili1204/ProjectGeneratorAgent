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
  let activeFileContent = '';
  let isFinished = false;
  let logBuffer = [];
  const MAX_LOG_LINES = 500;

  // 终端/文件列表交互状态
  let logFilter = 'all';        // all | warn | error | llm
  let autoScroll = true;
  let fileSearchQuery = '';

  // === SVG 图标常量（no-emoji-icons） ===
  const ICON = {
    clock: '<svg aria-hidden="true" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>',
    tool: '<svg aria-hidden="true" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"></path></svg>',
    brain: '<svg aria-hidden="true" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 1.98-3A2.5 2.5 0 0 1 9.5 2Z"></path><path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96.44 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-1.98-3A2.5 2.5 0 0 0 14.5 2Z"></path></svg>',
    file: '<svg aria-hidden="true" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>',
    git: '<svg aria-hidden="true" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="6" r="3"></circle><circle cx="6" cy="18" r="3"></circle><path d="M13 6h3a2 2 0 0 1 2 2v7"></path><line x1="6" y1="9" x2="6" y2="15"></line></svg>',
    coin: '<svg aria-hidden="true" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><path d="M12 6v12"></path><path d="M15 9.5a2.5 2.5 0 0 0-2.5-2.5h-1A2.5 2.5 0 0 0 9 9.5c0 1.38 1.12 2.5 2.5 2.5h1c1.38 0 2.5 1.12 2.5 2.5A2.5 2.5 0 0 1 12.5 17h-1A2.5 2.5 0 0 1 9 14.5"></path></svg>',
  };

  // 步骤状态矢量图标（白色 stroke，渲染在彩色节点圆点上；遵循 no-emoji-icons）
  const STEP_ICON = {
    completed: '<svg class="step-svg" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>',
    running: '<svg class="step-svg" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="2" x2="12" y2="6"></line><line x1="12" y1="18" x2="12" y2="22"></line><line x1="4.93" y1="4.93" x2="7.76" y2="7.76"></line><line x1="16.24" y1="16.24" x2="19.07" y2="19.07"></line><line x1="2" y1="12" x2="6" y2="12"></line><line x1="18" y1="12" x2="22" y2="12"></line><line x1="4.93" y1="19.07" x2="7.76" y2="16.24"></line><line x1="16.24" y1="7.76" x2="19.07" y2="4.93"></line></svg>',
    failed: '<svg class="step-svg" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>',
    waiting_checkpoint: '<svg class="step-svg" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="5" width="4" height="14" rx="1"></rect><rect x="14" y="5" width="4" height="14" rx="1"></rect></svg>',
    skipped: '<svg class="step-svg" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="13 17 18 12 13 7"></polyline><polyline points="6 17 11 12 6 7"></polyline></svg>',
  };

  // === 工具函数 ===
  function fileExt(path) {
    if (!path) return '';
    const parts = path.split('.');
    if (parts.length < 2) return '';
    return parts.pop().toLowerCase();
  }
  function fileBadge(path) {
    const ext = fileExt(path);
    return `<span class="file-type-badge" data-ext="${escapeHtml(ext || 'default')}" aria-hidden="true">${escapeHtml(ext ? ext.slice(0, 4) : '·')}</span>`;
  }
  function formatDuration(sec) {
    if (!sec || sec < 0.1) return '-';
    if (sec < 60) return `${sec.toFixed(1)}s`;
    const m = Math.floor(sec / 60), s = Math.round(sec % 60);
    return `${m}m${s.toString().padStart(2, '0')}s`;
  }
  function formatDurationLong(sec) {
    if (!sec) return '0s';
    if (sec < 60) return `${Math.round(sec)}s`;
    const m = Math.floor(sec / 60), s = Math.round(sec % 60);
    if (m < 60) return `${m}m${s}s`;
    const h = Math.floor(m / 60), mm = m % 60;
    return `${h}h${mm}m`;
  }
  function formatTokens(n) {
    if (!n) return '0';
    if (n < 1000) return `${n}`;
    if (n < 1000000) return `${(n / 1000).toFixed(1)}k`;
    return `${(n / 1000000).toFixed(2)}M`;
  }
  function basename(path) {
    if (!path) return '';
    const parts = path.split('/');
    return parts[parts.length - 1] || path;
  }

  // === 弹窗无障碍：ESC 关闭、焦点陷阱、关闭动画、焦点回归 ===
  const FOCUSABLE = 'button, [href], input, textarea, select, [tabindex]:not([tabindex="-1"])';
  function setupModal(overlay, opts = {}) {
    const previouslyFocused = document.activeElement;
    const close = () => {
      overlay.classList.add('closing');
      document.removeEventListener('keydown', onKeydown);
      setTimeout(() => {
        overlay.remove();
        if (previouslyFocused && previouslyFocused.focus) previouslyFocused.focus();
        if (opts.onClose) opts.onClose();
      }, 180);
    };
    const onKeydown = (e) => {
      if (e.key === 'Escape') { e.preventDefault(); close(); return; }
      if (e.key === 'Tab') {
        const focusables = overlay.querySelectorAll(FOCUSABLE);
        if (!focusables.length) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault(); last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault(); first.focus();
        }
      }
    };
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    overlay.querySelectorAll('[data-modal-close]').forEach(b => b.addEventListener('click', close));
    document.addEventListener('keydown', onKeydown);
    setTimeout(() => {
      const f = overlay.querySelector(FOCUSABLE);
      if (f) f.focus();
    }, 50);
    return { close };
  }

  // === 加载工作流状态 ===
  async function loadState() {
    try {
      const data = await API.getWorkflow(workflowId);
      state = data;
      renderHeader();
      renderTimeline();
      if (!isFinished && (state.status === 'running' || state.status === 'paused')) {
        ensureWebSocket();
      }
      if (state.logs && state.logs.length) {
        if (logBuffer.length === 0) {
          state.logs.forEach(entry => appendLog(entry, true));
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

  // === 渲染：顶部 + 子头部（进度/指标/操作） ===
  function renderHeader() {
    $('wf-title').textContent = state.title || '(无标题)';
    $('wf-id').textContent = '#' + state.workflow_id.substring(0, 8);
    const statusEl = $('wf-status');
    statusEl.className = `status-badge status-${state.status}`;
    statusEl.textContent = statusText(state.status);

    renderSubheader();
    renderCheckpointBanner();

    if (state.status === 'completed' || state.status === 'failed') {
      isFinished = true;
      if (state.status === 'completed') toast('工作流已完成', 'success');
      else toast('工作流失败', 'error');
    }
  }

  function renderSubheader() {
    const steps = state.steps || [];
    const total = steps.length;
    const done = steps.filter(s => ['completed', 'failed', 'skipped'].includes(s.status)).length;
    const pct = total ? Math.round((done / total) * 100) : 0;

    // 进度条
    const fill = $('wf-progress-fill');
    fill.style.width = `${pct}%`;
    fill.className = 'wf-progress-fill';
    if (state.status === 'completed') fill.classList.add('done');
    else if (state.status === 'failed') fill.classList.add('failed');
    $('wf-progress-text').textContent = total ? `${done} / ${total} · ${pct}%` : '- / -';
    $('step-counter').textContent = total ? `${done}/${total}` : '-';

    // 指标汇总
    const totalDur = steps.reduce((a, s) => a + (s.duration_sec || 0), 0);
    const totalTokens = steps.reduce((a, s) => a + (s.tokens || 0), 0);
    const totalLlm = steps.reduce((a, s) => a + (s.llm_calls || 0), 0);
    const cost = (typeof state.computed_cost_usd === 'number')
      ? state.computed_cost_usd
      : (state.total_cost_usd || 0);
    $('wf-metrics').innerHTML = `
      <span class="wf-metric" title="总耗时">${ICON.clock}<strong>${formatDurationLong(totalDur)}</strong></span>
      <span class="wf-metric" title="LLM 调用次数">${ICON.brain}<strong>${totalLlm}</strong></span>
      <span class="wf-metric" title="累计 Token">${ICON.file}<strong>${formatTokens(totalTokens)}</strong></span>
      ${cost > 0 ? `<span class="wf-metric" title="预估成本">${ICON.coin}<strong>$${cost.toFixed(4)}</strong></span>` : ''}
    `;
  }

  // === 渲染：时间轴（含步骤统计） ===
  function renderTimeline() {
    const container = $('timeline');
    if (!state.steps || !state.steps.length) {
      container.innerHTML = '<div class="empty-state" style="padding: 20px;"><div class="empty-state-text">无步骤</div></div>';
      return;
    }
    container.innerHTML = state.steps.map((s, i) => {
      const canRerun = !['pending', 'running', 'waiting_checkpoint'].includes(s.status);
      const rerunBtn = canRerun
        ? `<button class="btn btn-ghost btn-xs rerun-btn" data-skill="${escapeHtml(s.skill_name)}" data-name="${escapeHtml(s.display_name || s.skill_name)}" title="重新生成此步骤" aria-label="重新生成 ${escapeHtml(s.display_name || s.skill_name)}">
            <svg aria-hidden="true" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"></polyline><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path></svg>
            重跑
          </button>`
        : '';

      // 步骤指标：统一为胶囊 chip（含 commit），仅在有数据时显示
      const stats = [];
      if (s.duration_sec && s.duration_sec >= 0.1) stats.push(`<span class="step-stat" title="耗时">${ICON.clock}<span>${formatDuration(s.duration_sec)}</span></span>`);
      if (s.llm_calls) stats.push(`<span class="step-stat" title="LLM 调用">${ICON.brain}<span>${s.llm_calls}</span></span>`);
      if (s.tool_calls) stats.push(`<span class="step-stat" title="工具调用">${ICON.tool}<span>${s.tool_calls}</span></span>`);
      if (s.output_files && s.output_files.length) stats.push(`<span class="step-stat has-output" title="产出文件">${ICON.file}<span>${s.output_files.length}</span></span>`);
      if (s.commit_hash) stats.push(`<span class="step-stat has-commit" title="Git commit">${ICON.git}<code>${escapeHtml(s.commit_hash.substring(0, 7))}</code></span>`);
      const statsHtml = stats.length ? `<div class="step-stats">${stats.join('')}</div>` : '';

      const errHtml = s.error_message
        ? `<div class="step-error">${escapeHtml(s.error_message.substring(0, 160))}</div>`
        : '';

      const skillVer = s.skill_version ? ` · v${escapeHtml(s.skill_version)}` : '';
      const skillText = escapeHtml(s.skill_name) + skillVer;
      const name = escapeHtml(s.display_name || s.skill_name);
      const stepSvg = STEP_ICON[s.status] || '';

      return `
      <div class="timeline-step status-${escapeHtml(s.status)}" style="animation-delay:${i * 30}ms">
        <div class="step-icon" aria-hidden="true">${stepSvg}</div>
        <div class="step-body">
          <div class="step-row-main">
            <span class="step-name" title="${name}">${name}</span>
            ${rerunBtn}
          </div>
          <div class="step-row-meta">
            <span class="step-skill" title="${skillText}">${skillText}</span>
            <span class="step-status-pill">${stepStatusText(s.status)}</span>
          </div>
          ${statsHtml}
          ${errHtml}
        </div>
      </div>`;
    }).join('');

    container.querySelectorAll('.rerun-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        showRerunModal(btn.getAttribute('data-skill'), btn.getAttribute('data-name'));
      });
    });
  }

  // === 重新生成弹窗 ===
  function showRerunModal(skillName, displayName) {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', `重新生成：${displayName}`);
    overlay.innerHTML = `
      <div class="modal">
        <div class="modal-header">重新生成：${escapeHtml(displayName)}</div>
        <div class="modal-body">
          <div style="margin-bottom: 16px; padding: 12px; background: var(--warning-light); border-radius: 8px; border-left: 3px solid var(--warning);">
            <strong>注意：</strong>重跑此步骤将<strong>级联重跑所有后续步骤</strong>。之前后续步骤的产出将被覆盖。
          </div>
          <div class="form-group">
            <label class="form-label">选项</label>
            <label class="form-checkbox" style="margin-bottom: 8px;">
              <input type="checkbox" id="rerun-clean">
              <span>清理产物后重跑（删除该步骤之前的产出再重新生成）</span>
            </label>
            <label class="form-checkbox">
              <input type="checkbox" id="rerun-latest">
              <span>使用最新 Skill 版本（升级到最新 SKILL.md）</span>
            </label>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-ghost btn-sm" id="rerun-cancel" data-modal-close>取消</button>
          <button class="btn btn-primary btn-sm" id="rerun-confirm">确认重跑</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);

    const { close } = setupModal(overlay);

    $('rerun-confirm').addEventListener('click', async () => {
      const clean = $('rerun-clean').checked;
      const latest = $('rerun-latest').checked;
      const btn = $('rerun-confirm');
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner" aria-hidden="true"></span> 提交中...';
      try {
        await API.rerunStep(workflowId, skillName, { clean, latest });
        toast(`已触发重新生成：${displayName}`, 'success');
        close();
        isFinished = false;
        setTimeout(() => { loadState(); loadFiles(); ensureWebSocket(); }, 500);
      } catch (e) {
        toast(`重跑失败: ${e.message}`, 'error');
        btn.disabled = false;
        btn.textContent = '确认重跑';
      }
    });
  }

  // === 渲染：文件列表（图标 + 搜索过滤） ===
  function renderFileList() {
    const container = $('file-list');
    $('file-count').textContent = files.length;
    if (!files.length) {
      container.innerHTML = '<div class="empty-state" style="padding: 20px;"><div class="empty-state-text">暂无文件</div></div>';
      return;
    }
    const q = fileSearchQuery.trim().toLowerCase();
    const filtered = q ? files.filter(f => (f.path || '').toLowerCase().includes(q)) : files;
    if (!filtered.length) {
      container.innerHTML = `<div class="empty-state" style="padding: 20px;"><div class="empty-state-text">无匹配文件</div><div class="empty-state-hint">换个关键词试试</div></div>`;
      return;
    }
    container.innerHTML = filtered.map(f => `
      <div class="file-item-row ${activeFile === f.path ? 'active' : ''}" data-path="${escapeHtml(f.path)}" tabindex="0" role="button" aria-label="查看文件 ${escapeHtml(f.path)}" title="${escapeHtml(f.path)}">
        ${fileBadge(f.path)}
        <span class="file-item-name">${escapeHtml(f.path)}</span>
        <span class="file-item-size">${formatSize(f.size)}</span>
      </div>
    `).join('');
    container.querySelectorAll('.file-item-row').forEach(el => {
      const open = () => loadFileContent(el.getAttribute('data-path'));
      el.addEventListener('click', open);
      el.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); }
      });
    });
  }

  // === 渲染：带行号的代码块 ===
  function renderCodeBlock(content) {
    const lines = content.split('\n');
    // 超长文件跳过行号以保证性能
    if (lines.length > 2000) {
      return `<div class="file-content">${escapeHtml(content)}</div>`;
    }
    const gutter = lines.map((_, i) => `<span>${i + 1}</span>`).join('');
    return `
      <div class="code-block">
        <div class="code-gutter" aria-hidden="true">${gutter}</div>
        <pre class="code-content"><code>${escapeHtml(content)}</code></pre>
      </div>`;
  }

  // === 加载并显示文件内容 ===
  async function loadFileContent(path) {
    activeFile = path;
    renderFileList();
    const ext = fileExt(path);
    const badge = $('active-file-badge');
    badge.setAttribute('data-ext', ext || 'default');
    badge.textContent = ext ? ext.slice(0, 4) : '·';
    $('active-file-name').textContent = path;
    $('active-file-name').title = path;
    $('active-file-size').textContent = '';
    $('copy-btn').disabled = true;
    $('download-btn').disabled = true;
    const contentEl = $('output-content');
    contentEl.innerHTML = `<div class="output-empty"><span class="spinner spinner-lg" aria-hidden="true"></span><div style="margin-top:8px;">加载中...</div></div>`;

    try {
      const data = await API.readFile(workflowId, path);
      const content = data.content || '';
      activeFileContent = content;
      $('active-file-size').textContent = formatSize(data.size || content.length);
      $('copy-btn').disabled = false;
      $('download-btn').disabled = false;

      if (path.endsWith('.md')) {
        contentEl.innerHTML = `<div class="file-content markdown">${renderMarkdown(content)}</div>`;
      } else if (path.endsWith('.json')) {
        try {
          const obj = JSON.parse(content);
          contentEl.innerHTML = renderCodeBlock(JSON.stringify(obj, null, 2));
        } catch (e) {
          contentEl.innerHTML = renderCodeBlock(content);
        }
      } else {
        contentEl.innerHTML = renderCodeBlock(content);
      }
    } catch (e) {
      activeFileContent = '';
      contentEl.innerHTML = `<div class="output-empty"><div style="color: var(--danger);">加载失败: ${escapeHtml(e.message)}</div></div>`;
    }
  }

  // === 复制 / 下载 ===
  async function copyActiveFile() {
    if (!activeFileContent) return;
    try {
      await navigator.clipboard.writeText(activeFileContent);
      toast('已复制到剪贴板', 'success');
    } catch (e) {
      // 降级方案
      const ta = document.createElement('textarea');
      ta.value = activeFileContent;
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); toast('已复制到剪贴板', 'success'); }
      catch (err) { toast('复制失败', 'error'); }
      ta.remove();
    }
  }
  function downloadActiveFile() {
    if (!activeFile || !activeFileContent) return;
    const blob = new Blob([activeFileContent], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = basename(activeFile);
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  // === 渲染：检查点横幅 ===
  function renderCheckpointBanner() {
    const container = $('checkpoint-banner-container');
    const waiting = (state.steps || []).find(s => s.status === 'waiting_checkpoint');
    if (!waiting) { container.innerHTML = ''; return; }
    container.innerHTML = `
      <div class="checkpoint-banner">
        <div>
          <strong>等待检查点确认：</strong>
          ${escapeHtml(waiting.display_name || waiting.skill_name)} 已完成，请审核产出后选择通过或打回。
        </div>
        <div class="actions">
          <button class="btn btn-success btn-sm" id="cp-approve-btn">
            <svg aria-hidden="true" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>
            通过
          </button>
          <button class="btn btn-danger btn-sm" id="cp-reject-btn">
            <svg aria-hidden="true" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
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
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', title);
    overlay.innerHTML = `
      <div class="modal">
        <div class="modal-header">${title}</div>
        <div class="modal-body">
          <div class="form-group">
            <label class="form-label" for="cp-feedback">反馈内容</label>
            <textarea class="form-textarea" id="cp-feedback" rows="4" placeholder="${escapeHtml(placeholder)}"></textarea>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-ghost btn-sm" id="cp-cancel" data-modal-close>取消</button>
          <button class="btn ${btnClass} btn-sm" id="cp-confirm" ${!approved ? 'data-require-feedback="1"' : ''}>${btnText}</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);

    const { close } = setupModal(overlay);

    $('cp-confirm').addEventListener('click', async () => {
      const feedback = $('cp-feedback').value.trim();
      if (!approved && !feedback) {
        toast('打回必须填写反馈', 'warning');
        $('cp-feedback').focus();
        return;
      }
      const btn = $('cp-confirm');
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner" aria-hidden="true"></span> 提交中...';
      try {
        await API.submitCheckpoint(workflowId, { approved, feedback, run: approved });
        toast(approved ? '已通过，工作流恢复中' : '已打回', 'success');
        close();
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
    ws.onopen = () => setWsStatus('connected');
    ws.onmessage = (event) => {
      let data;
      try { data = JSON.parse(event.data); } catch (e) { return; }
      handleWsEvent(data);
    };
    ws.onerror = () => setWsStatus('error');
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
    if (!indicator || !text) return;  // 防御：DOM 尚未就绪或页面已卸载
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
      renderHeader(); renderTimeline(); loadFiles();
    } else if (etype === 'log') {
      appendLog(event);
      const msg = event.message || '';
      if (msg.includes('步骤完成') || msg.includes('步骤失败') ||
          msg.includes('工作流执行完成') || msg.includes('工作流失败') ||
          msg.includes('等待检查点')) {
        loadState(); loadFiles();
      }
    } else if (etype === 'checkpoint') {
      loadState();
    } else if (etype === 'finished') {
      isFinished = true;
      setWsStatus('disconnected');
      toast('工作流已完成', 'success');
      loadState(); loadFiles();
    } else if (etype === 'failed') {
      isFinished = true;
      setWsStatus('disconnected');
      toast('工作流失败', 'error');
      loadState(); loadFiles();
    } else if (etype === 'heartbeat') {
      // ignore
    } else if (etype === 'error') {
      toast(`服务器错误: ${event.message || ''}`, 'error');
    }
  }

  // === 追加日志到终端（含级别过滤与自动滚动） ===
  function matchesFilter(levelEl, isLlm) {
    if (logFilter === 'all') return true;
    if (logFilter === 'llm') return isLlm;
    return levelEl === logFilter;
  }
  function appendLog(entry, isHistory = false) {
    const ts = (entry.timestamp || '').substring(11, 19);
    const step = entry.step || '';
    const level = entry.level || 'info';
    const message = entry.message || '';
    const isLlm = /LLM|llm|调用.*模型|tool_call|function_call/i.test(message) || /llm/i.test(level);

    const visible = matchesFilter(level, isLlm);
    const line = document.createElement('div');
    line.className = `log-line level-${level}${isLlm ? ' level-llm' : ''}${visible ? '' : ' hidden'}`;
    line.dataset.level = level;
    line.dataset.llm = isLlm ? '1' : '0';
    line.innerHTML = `
      <span class="log-time">${escapeHtml(ts)}</span>
      <span class="log-step">${escapeHtml(step)}</span>
      <span class="log-message">${escapeHtml(message)}</span>`;
    const body = $('terminal-body');
    body.appendChild(line);
    logBuffer.push(line);
    if (logBuffer.length > MAX_LOG_LINES) {
      const old = logBuffer.shift();
      if (old && old.parentNode) old.parentNode.removeChild(old);
    }
    $('log-count').textContent = logBuffer.length;
    if (autoScroll && visible) {
      body.scrollTop = body.scrollHeight;
    }
  }

  // === 日志过滤 / 自动滚动切换 ===
  function applyLogFilter() {
    logBuffer.forEach(line => {
      const level = line.dataset.level;
      const isLlm = line.dataset.llm === '1';
      const visible = matchesFilter(level, isLlm);
      line.classList.toggle('hidden', !visible);
    });
    if (autoScroll) $('terminal-body').scrollTop = $('terminal-body').scrollHeight;
  }

  // === 初始化 ===
  async function init() {
    $('refresh-btn').addEventListener('click', () => { loadState(); loadFiles(); });

    // 导出 / 删除
    $('wf-export-btn').addEventListener('click', () => {
      API.exportWorkflow(workflowId);
      toast('正在导出...', 'info');
    });
    $('wf-delete-btn').addEventListener('click', async () => {
      if (!confirm('确定删除此工作流？所有文件将被清除。')) return;
      try {
        await API.deleteWorkflow(workflowId);
        toast('已删除', 'success');
        setTimeout(() => location.href = '/', 600);
      } catch (e) {
        toast(`删除失败: ${e.message}`, 'error');
      }
    });

    // 复制 / 下载
    $('copy-btn').addEventListener('click', copyActiveFile);
    $('download-btn').addEventListener('click', downloadActiveFile);

    // 日志级别过滤
    document.querySelectorAll('.log-filter').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.log-filter').forEach(b => {
          b.classList.remove('active');
          b.setAttribute('aria-pressed', 'false');
        });
        btn.classList.add('active');
        btn.setAttribute('aria-pressed', 'true');
        logFilter = btn.getAttribute('data-level');
        applyLogFilter();
      });
    });

    // 自动滚动切换
    $('autoscroll-btn').addEventListener('click', () => {
      autoScroll = !autoScroll;
      const btn = $('autoscroll-btn');
      btn.classList.toggle('active', autoScroll);
      btn.setAttribute('aria-pressed', autoScroll ? 'true' : 'false');
      btn.setAttribute('title', autoScroll ? '自动滚动（开）' : '自动滚动（关）');
      if (autoScroll) $('terminal-body').scrollTop = $('terminal-body').scrollHeight;
    });

    // 文件搜索
    $('file-search-input').addEventListener('input', (e) => {
      fileSearchQuery = e.target.value;
      renderFileList();
    });

    // 先加载状态（确定是否需要 WS），再加载文件，最后按需建立 WS
    // 已完成/失败的工作流 isFinished=true，ensureWebSocket 会直接返回，避免无谓连接
    await loadState();
    loadFiles();
    ensureWebSocket();
  }

  // 兼容 DOMContentLoaded 已触发的情况（脚本位于 body 末尾时可能已就绪）
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // 页面卸载时关闭 WS
  window.addEventListener('beforeunload', () => {
    if (ws) { ws.onclose = null; ws.close(); }
  });
})();
