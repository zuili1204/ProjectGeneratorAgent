// === 主页逻辑 ===

(function () {
  const $ = (id) => document.getElementById(id);
  let refreshTimer = null;

  // 内联 SVG 图标（替代 emoji，遵循 no-emoji-icons）
  const ICON = {
    template: '<svg aria-hidden="true" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"></rect><line x1="3" y1="9" x2="21" y2="9"></line><line x1="9" y1="21" x2="9" y2="9"></line></svg>',
    step: '<svg aria-hidden="true" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>',
    clock: '<svg aria-hidden="true" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>',
  };

  // === 项目类型 → 技术栈面板切换 ===
  function switchTechStack(type) {
    ['fullstack', 'frontend_only', 'cli', 'script'].forEach(t => {
      const el = $(`ts-${t}`);
      if (el) el.classList.toggle('active', t === type);
    });
  }

  // === Chip 选择（含键盘支持：Enter/Space） ===
  function initChips() {
    document.querySelectorAll('.chip-group').forEach(group => {
      group.addEventListener('click', (e) => {
        const chip = e.target.closest('.chip');
        if (!chip) return;
        activateChip(group, chip);
      });
      // 键盘可达性：Enter / Space 触发
      group.addEventListener('keydown', (e) => {
        const chip = e.target.closest('.chip');
        if (!chip) return;
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          activateChip(group, chip);
        }
      });
    });
  }

  function activateChip(group, chip) {
    group.querySelectorAll('.chip').forEach(c => {
      c.classList.remove('active');
      c.setAttribute('aria-pressed', 'false');
    });
    chip.classList.add('active');
    chip.setAttribute('aria-pressed', 'true');
  }

  // === 收集技术栈 ===
  function collectTechStack() {
    const type = $('req-project-type').value;
    const activeGroup = $(`ts-${type}`);
    if (!activeGroup) return {};
    const stack = {};
    activeGroup.querySelectorAll('.chip-group').forEach(g => {
      const name = g.getAttribute('data-name');
      const active = g.querySelector('.chip.active');
      if (name && active) stack[name] = active.getAttribute('data-val');
    });
    return stack;
  }

  // === 骨架屏占位（加载中） ===
  function renderSkeleton(count = 3) {
    const container = $('workflow-list');
    container.innerHTML = Array.from({ length: count }).map(() => `
      <div class="workflow-item" style="cursor:default;animation:none;" aria-hidden="true">
        <div class="workflow-item-header">
          <div class="skeleton skeleton-text" style="height:16px;width:60%;margin:0;"></div>
          <div class="skeleton" style="height:18px;width:60px;border-radius:999px;"></div>
        </div>
        <div class="skeleton skeleton-text" style="width:40%;margin-top:10px;"></div>
        <div class="skeleton skeleton-text" style="width:80%;"></div>
      </div>
    `).join('');
  }

  // === 加载工作流列表 ===
  async function loadWorkflows() {
    renderSkeleton();
    try {
      const data = await API.listWorkflows();
      const list = data.workflows || [];
      renderWorkflows(list);
      $('workflow-count').textContent = list.length ? `${list.length} 个` : '';
    } catch (e) {
      toast(`加载失败: ${e.message}`, 'error');
      console.error(e);
      renderWorkflows([]);
    }
  }

  function renderWorkflows(list) {
    const container = $('workflow-list');
    if (!list.length) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">
            <svg aria-hidden="true" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"></path><path d="M7 14l3-3 3 3 5-5"></path></svg>
          </div>
          <div class="empty-state-text">暂无工作流</div>
          <div class="empty-state-hint">在左侧描述需求并启动即可</div>
        </div>`;
      return;
    }
    container.innerHTML = list.map((w, i) => `
      <div class="workflow-item" data-id="${escapeHtml(w.workflow_id)}" style="animation-delay:${i * 40}ms" tabindex="0" role="button" aria-label="打开工作流：${escapeHtml(w.title)}">
        <div class="workflow-item-header">
          <div class="workflow-title">${escapeHtml(w.title)}</div>
          <span class="status-badge status-${escapeHtml(w.status)}">${statusText(w.status)}</span>
        </div>
        <div class="workflow-meta">
          <span class="meta-item">${ICON.template}${escapeHtml(w.template)}</span>
          ${w.current_step ? `<span class="meta-item">${ICON.step}${escapeHtml(w.current_step)}</span>` : ''}
          <span class="meta-item">${ICON.clock}${formatTime(w.created_at)}</span>
          <span class="workflow-id">${escapeHtml(w.workflow_id.substring(0, 12))}...</span>
        </div>
        <div class="workflow-item-actions">
          <button class="btn btn-ghost btn-sm wf-export-btn" data-id="${escapeHtml(w.workflow_id)}" title="导出工作流" aria-label="导出工作流 ${escapeHtml(w.title)}">
            <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
            导出
          </button>
          <button class="btn btn-ghost btn-sm wf-delete-btn" data-id="${escapeHtml(w.workflow_id)}" title="删除工作流" aria-label="删除工作流 ${escapeHtml(w.title)}">
            <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
            删除
          </button>
        </div>
      </div>
    `).join('');

    const openItem = (el) => {
      const id = el.getAttribute('data-id');
      location.href = `/workflow.html?id=${encodeURIComponent(id)}`;
    };

    container.querySelectorAll('.workflow-item').forEach(el => {
      el.addEventListener('click', (e) => {
        if (e.target.closest('.wf-export-btn, .wf-delete-btn')) return;
        openItem(el);
      });
      // 键盘可达性
      el.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          openItem(el);
        }
      });
    });

    // 导出按钮
    container.querySelectorAll('.wf-export-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const id = btn.getAttribute('data-id');
        API.exportWorkflow(id);
        toast('正在导出...', 'info');
      });
    });

    // 删除按钮
    container.querySelectorAll('.wf-delete-btn').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const id = btn.getAttribute('data-id');
        if (!confirm('确定删除此工作流？所有文件将被清除。')) return;
        try {
          await API.deleteWorkflow(id);
          toast('已删除', 'success');
          loadWorkflows();
        } catch (err) {
          toast(`删除失败: ${err.message}`, 'error');
        }
      });
    });
  }

  // === 创建工作流 ===
  async function startWorkflow() {
    const title = $('req-title').value.trim();
    if (!title) {
      toast('请输入需求', 'warning');
      $('req-title').focus();
      return;
    }
    const projectType = $('req-project-type').value;
    const designStyle = $('req-design-style').value;
    const designStyleDesc = designStyle === 'custom'
      ? $('req-design-style-desc').value.trim()
      : '';
    const techStack = collectTechStack();
    const enableCheckpoints = $('req-checkpoint').checked;
    const autoProceed = $('req-auto').checked;

    if (designStyle === 'custom' && !designStyleDesc) {
      toast('请描述自定义设计风格', 'warning');
      $('req-design-style-desc').focus();
      return;
    }

    const btn = $('start-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner" aria-hidden="true"></span><span>创建中...</span>';

    try {
      const data = await API.createWorkflow({
        title,
        template: 'grad_project',
        project_type: projectType,
        design_style: designStyle,
        design_style_desc: designStyleDesc,
        tech_stack: techStack,
        enable_checkpoints: enableCheckpoints,
        auto_proceed: autoProceed,
      });
      const workflowId = data.workflow_id;
      toast('工作流已创建，正在启动...', 'success');

      await API.startWorkflow(workflowId);
      toast('工作流已启动', 'success');

      setTimeout(() => {
        location.href = `/workflow.html?id=${encodeURIComponent(workflowId)}`;
      }, 500);
    } catch (e) {
      toast(`启动失败: ${e.message}`, 'error');
      console.error(e);
    } finally {
      btn.disabled = false;
      btn.innerHTML = `
        <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
        启动工作流`;
    }
  }

  // === 自动刷新 ===
  function startAutoRefresh() {
    if (refreshTimer) clearInterval(refreshTimer);
    refreshTimer = setInterval(() => {
      if (!document.hidden) loadWorkflows();
    }, 5000);
  }

  // === 初始化 ===
  document.addEventListener('DOMContentLoaded', () => {
    $('start-btn').addEventListener('click', startWorkflow);
    $('refresh-btn').addEventListener('click', loadWorkflows);

    // 项目类型切换 → 技术栈面板切换
    $('req-project-type').addEventListener('change', (e) => {
      switchTechStack(e.target.value);
    });

    // 设计风格切换 → 自定义描述显示/隐藏
    $('req-design-style').addEventListener('change', (e) => {
      $('req-design-style-desc').classList.toggle('active', e.target.value === 'custom');
    });

    // Ctrl/Cmd + Enter 快捷启动
    $('req-title').addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        startWorkflow();
      }
    });

    // 需求示例快速填充
    document.querySelectorAll('.quick-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        $('req-title').value = chip.getAttribute('data-req');
        $('req-title').focus();
      });
    });

    initChips();
    switchTechStack('fullstack');
    loadWorkflows();
    startAutoRefresh();
  });
})();
