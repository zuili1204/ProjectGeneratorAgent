// === 主页逻辑 ===

(function () {
  const $ = (id) => document.getElementById(id);
  let refreshTimer = null;

  // === 项目类型 → 技术栈面板切换 ===
  function switchTechStack(type) {
    ['fullstack', 'frontend_only', 'cli', 'script'].forEach(t => {
      const el = $(`ts-${t}`);
      if (el) el.classList.toggle('active', t === type);
    });
  }

  // === Chip 选择 ===
  function initChips() {
    document.querySelectorAll('.chip-group').forEach(group => {
      group.addEventListener('click', (e) => {
        if (!e.target.classList.contains('chip')) return;
        // 同组内单选
        group.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
        e.target.classList.add('active');
      });
    });
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

  // === 加载工作流列表 ===
  async function loadWorkflows() {
    try {
      const data = await API.listWorkflows();
      const list = data.workflows || [];
      renderWorkflows(list);
      $('workflow-count').textContent = list.length ? `${list.length} 个` : '';
    } catch (e) {
      toast(`加载失败: ${e.message}`, 'error');
      console.error(e);
    }
  }

  function renderWorkflows(list) {
    const container = $('workflow-list');
    if (!list.length) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">∅</div>
          <div class="empty-state-text">暂无工作流，从左侧创建一个吧</div>
        </div>`;
      return;
    }
    container.innerHTML = list.map(w => `
      <div class="workflow-item" data-id="${escapeHtml(w.workflow_id)}">
        <div class="workflow-item-header">
          <div class="workflow-title">${escapeHtml(w.title)}</div>
          <span class="status-badge status-${escapeHtml(w.status)}">${statusText(w.status)}</span>
        </div>
        <div class="workflow-meta">
          <span>📝 ${escapeHtml(w.template)}</span>
          ${w.current_step ? `<span>⚙️ ${escapeHtml(w.current_step)}</span>` : ''}
          <span>🕐 ${formatTime(w.created_at)}</span>
          <span class="workflow-id">${escapeHtml(w.workflow_id.substring(0, 12))}...</span>
        </div>
        <div class="workflow-item-actions">
          <button class="btn btn-ghost btn-sm wf-export-btn" data-id="${escapeHtml(w.workflow_id)}" title="导出">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
            导出
          </button>
          <button class="btn btn-ghost btn-sm wf-delete-btn" data-id="${escapeHtml(w.workflow_id)}" title="删除">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
            删除
          </button>
        </div>
      </div>
    `).join('');

    container.querySelectorAll('.workflow-item').forEach(el => {
      el.addEventListener('click', (e) => {
        // 不要在点击按钮时跳转
        if (e.target.closest('.wf-export-btn, .wf-delete-btn')) return;
        const id = el.getAttribute('data-id');
        location.href = `/workflow.html?id=${encodeURIComponent(id)}`;
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
    btn.innerHTML = '<span class="text-sm">创建中...</span>';

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
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
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

    initChips();
    switchTechStack('fullstack');
    loadWorkflows();
    startAutoRefresh();
  });
})();
