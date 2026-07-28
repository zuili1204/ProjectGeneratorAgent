// === API 封装 ===
// 所有后端调用的统一入口

const API = (() => {
  // 自动推断后端地址：与页面同源
  const BASE = '';
  const TOKEN_KEY = 'pga_server_token';

  // === 服务令牌（localStorage，仅浏览器本地，不发给后端当配置） ===
  function getToken() {
    try { return localStorage.getItem(TOKEN_KEY) || ''; } catch (e) { return ''; }
  }
  function setToken(token) {
    try {
      if (token) localStorage.setItem(TOKEN_KEY, token);
      else localStorage.removeItem(TOKEN_KEY);
    } catch (e) { /* localStorage 不可用时静默 */ }
  }
  function hasToken() { return !!getToken(); }

  async function request(method, path, body) {
    const opts = {
      method,
      headers: { 'Content-Type': 'application/json' },
    };
    const token = getToken();
    if (token) opts.headers['Authorization'] = `Bearer ${token}`;
    if (body !== undefined) opts.body = JSON.stringify(body);
    const resp = await fetch(BASE + path, opts);
    // 401：令牌缺失或无效 → 引导到设置页填写
    if (resp.status === 401) {
      const onSettings = location.pathname.endsWith('/settings.html');
      if (!onSettings) {
        toast('服务令牌缺失或无效，正在跳转设置页', 'error');
        location.href = '/settings.html?auth=1';
      }
      throw new Error('未授权：缺少或错误的 Authorization 头');
    }
    let data;
    try { data = await resp.json(); } catch (e) { data = null; }
    if (!resp.ok) {
      const msg = (data && data.detail) || resp.statusText || `HTTP ${resp.status}`;
      throw new Error(msg);
    }
    return data;
  }

  return {
    // 服务令牌
    getToken,
    setToken,
    hasToken,

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
    rerunStep: (id, skill, params = {}) => {
      const qs = new URLSearchParams();
      if (params.clean) qs.set('clean', 'true');
      if (params.latest) qs.set('latest', 'true');
      const q = qs.toString();
      return request('POST', `/api/workflows/${id}/rerun/${skill}${q ? '?' + q : ''}`);
    },

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

// Toast 提示（aria-live polite，不抢焦点；3-5s 自动消失）
// 复用单一 aria-live 容器，便于屏幕阅读器播报。
function _toastRegion() {
  let r = document.getElementById('toast-region');
  if (!r) {
    r = document.createElement('div');
    r.id = 'toast-region';
    r.setAttribute('aria-live', 'polite');
    r.setAttribute('aria-atomic', 'true');
    r.className = 'sr-only';
    document.body.appendChild(r);
  }
  return r;
}

function toast(message, type = '') {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.setAttribute('role', type === 'error' ? 'alert' : 'status');
  // 图标 + 文本，避免仅靠颜色传达状态（color-not-decorative-only）
  const icon = type === 'success' ? '<svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>'
    : type === 'error' ? '<svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>'
    : type === 'warning' ? '<svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>'
    : '';
  el.innerHTML = `${icon}<span>${escapeHtml(message)}</span>`;
  document.body.appendChild(el);
  // 供屏幕阅读器播报的纯文本
  _toastRegion().textContent = message;

  const DURATION = type === 'error' ? 4000 : 2800;
  setTimeout(() => {
    el.classList.add('leaving');
    setTimeout(() => el.remove(), 280);
  }, DURATION);
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
