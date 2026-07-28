// === API 封装 ===
// 所有后端调用的统一入口

const API = (() => {
  // 自动推断后端地址：与页面同源
  const BASE = '';

  async function request(method, path, body) {
    const opts = {
      method,
      headers: { 'Content-Type': 'application/json' },
    };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const resp = await fetch(BASE + path, opts);
    let data;
    try { data = await resp.json(); } catch (e) { data = null; }
    if (!resp.ok) {
      const msg = (data && data.detail) || resp.statusText || `HTTP ${resp.status}`;
      throw new Error(msg);
    }
    return data;
  }

  return {
    // 健康检查
    health: () => request('GET', '/api/health'),

    // === 工作流 ===
    createWorkflow: (payload) => request('POST', '/api/workflows', payload),
    startWorkflow: (id) => request('POST', `/api/workflows/${id}/start`),
    listWorkflows: () => request('GET', '/api/workflows'),
    getWorkflow: (id) => request('GET', `/api/workflows/${id}`),
    deleteWorkflow: (id) => request('DELETE', `/api/workflows/${id}`),
    exportWorkflow: (id) => window.open(`/api/workflows/${id}/export`, '_blank'),
    listFiles: (id) => request('GET', `/api/workflows/${id}/files`),
    readFile: (id, path) => request('GET', `/api/workflows/${id}/files/${path}`),
    submitCheckpoint: (id, payload) => request('POST', `/api/workflows/${id}/checkpoint`, payload),
    rerunStep: (id, skill) => request('POST', `/api/workflows/${id}/rerun/${skill}`),

    // === 模板 / Skills ===
    getTemplates: () => request('GET', '/api/templates'),
    getSkills: () => request('GET', '/api/skills'),

    // === 配置 ===
    getConfig: () => request('GET', '/api/config'),
    setConfig: (key, value) => request('PUT', '/api/config', { key, value }),

    // === WebSocket ===
    wsUrl: (id) => {
      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
      return `${proto}//${location.host}/ws/workflows/${id}`;
    },
  };
})();

// === 工具函数 ===

function escapeHtml(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

function formatTime(iso) {
  if (!iso) return '-';
  try {
    const d = new Date(iso);
    return d.toLocaleString('zh-CN', { hour12: false });
  } catch (e) { return iso; }
}

function formatTimeShort(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString('zh-CN', { hour12: false });
  } catch (e) { return ''; }
}

function statusText(status) {
  const map = {
    pending: '待运行',
    running: '运行中',
    paused: '已暂停',
    completed: '已完成',
    failed: '失败',
  };
  return map[status] || status;
}

function stepStatusText(status) {
  const map = {
    pending: '待执行',
    running: '执行中',
    waiting_checkpoint: '等待确认',
    completed: '已完成',
    failed: '失败',
    skipped: '已跳过',
  };
  return map[status] || status;
}

// Toast 提示
function toast(message, type = '') {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = message;
  document.body.appendChild(el);
  setTimeout(() => {
    el.style.opacity = '0';
    el.style.transition = 'opacity 0.3s';
    setTimeout(() => el.remove(), 300);
  }, 2500);
}

// 简易 markdown 渲染（仅基础语法）
function renderMarkdown(md) {
  if (!md) return '';
  let html = escapeHtml(md);
  // 代码块
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (m, lang, code) =>
    `<pre class="md-code"><code>${code}</code></pre>`);
  // 标题
  html = html.replace(/^### (.+)$/gm, '<h4>$1</h4>');
  html = html.replace(/^## (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^# (.+)$/gm, '<h2>$1</h2>');
  // 粗体 / 斜体
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
  // 行内代码
  html = html.replace(/`([^`]+)`/g, '<code class="md-inline">$1</code>');
  // 列表
  html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
  html = html.replace(/(<li>[\s\S]+?<\/li>)/g, '<ul>$1</ul>');
  // 段落
  html = html.split(/\n\n+/).map(p => {
    if (p.startsWith('<') || p.trim() === '') return p;
    return `<p>${p.replace(/\n/g, '<br>')}</p>`;
  }).join('\n');
  return html;
}
