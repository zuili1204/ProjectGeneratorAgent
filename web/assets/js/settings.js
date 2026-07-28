// === 设置页逻辑 ===

(function () {
  const $ = (id) => document.getElementById(id);

  // 配置项 key 列表（与后端对应）
  const CONFIG_KEYS = [
    'llm_base_url',
    'llm_api_key',
    'llm_model',
    'llm_timeout',
    'llm_temperature',
    'llm_max_tokens',
    'agent_max_iter',
    'checkpoint_timeout',
  ];

  // 默认值（与后端 config.py 对齐）
  const DEFAULTS = {
    llm_base_url: 'https://api.deepseek.com/v1',
    llm_model: 'deepseek-chat',
    llm_timeout: '600',
    llm_temperature: '0.7',
    llm_max_tokens: '8192',
    agent_max_iter: '30',
    checkpoint_timeout: '600',
  };

  // === 加载配置 ===
  async function loadConfig() {
    try {
      const data = await API.getConfig();
      const cfg = data.config || {};
      $('cfg-path').value = data.path || '';

      CONFIG_KEYS.forEach(key => {
        const el = $(`cfg-${key}`);
        if (!el) return;
        // API 返回的 api_key 是脱敏的（如 sk-xxx...xxxx），填入占位
        if (key === 'llm_api_key') {
          const v = cfg[key];
          if (v && v.includes('...')) {
            el.value = '';
            el.placeholder = v + '（已配置，重新输入覆盖）';
          } else if (v) {
            el.value = v;
          }
        } else {
          el.value = cfg[key] !== undefined ? cfg[key] : (DEFAULTS[key] || '');
        }
      });
    } catch (e) {
      toast(`加载配置失败: ${e.message}`, 'error');
      console.error(e);
    }
  }

  // === 保存配置 ===
  async function saveConfig() {
    const btn = $('save-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner" aria-hidden="true"></span><span>保存中...</span>';

    try {
      // 逐项保存（仅保存有值或与默认不同的项）
      const promises = CONFIG_KEYS.map(async (key) => {
        const el = $(`cfg-${key}`);
        if (!el) return;
        let value = el.value.trim();
        // api_key 为空时跳过（保留已有值）
        if (key === 'llm_api_key' && !value) return;
        // 数值字段校验
        if (['llm_timeout', 'llm_max_tokens', 'agent_max_iter', 'checkpoint_timeout'].includes(key)) {
          if (value && isNaN(Number(value))) {
            throw new Error(`${key} 必须是数字`);
          }
        }
        if (['llm_temperature'].includes(key)) {
          if (value && isNaN(Number(value))) {
            throw new Error(`${key} 必须是数字`);
          }
        }
        if (value) {
          await API.setConfig(key, value);
        }
      });
      await Promise.all(promises);
      toast('配置已保存', 'success');
      // 重新加载（让 api_key 显示脱敏形式）
      setTimeout(loadConfig, 300);
    } catch (e) {
      toast(`保存失败: ${e.message}`, 'error');
      console.error(e);
    } finally {
      btn.disabled = false;
      btn.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path><polyline points="17 21 17 13 7 13 7 21"></polyline><polyline points="7 3 7 8 15 8"></polyline></svg>
        保存全部`;
    }
  }

  // === 服务令牌 ===
  function maskToken(t) {
    if (!t) return '';
    return t.length > 12 ? t.slice(0, 6) + '••••' + t.slice(-4) : '已配置';
  }

  function loadServerToken() {
    const t = API.getToken();
    const el = $('cfg-server_token');
    const status = $('token-status');
    if (t) {
      el.value = '';
      el.placeholder = maskToken(t) + '（已配置，重新输入覆盖）';
      status.textContent = '✓ 已配置';
      status.style.color = 'var(--success)';
    } else {
      el.placeholder = '粘贴服务令牌（如 B0Br...）';
      status.textContent = '未配置，API 调用将被拒绝';
      status.style.color = 'var(--danger)';
    }
  }

  function saveServerToken() {
    const el = $('cfg-server_token');
    const val = el.value.trim();
    if (!val) {
      toast('请输入服务令牌', 'error');
      return;
    }
    API.setToken(val);
    toast('服务令牌已保存', 'success');
    loadServerToken();
    // 移除 URL 中的 auth=1 标记
    if (location.search.includes('auth=1')) {
      history.replaceState(null, '', '/settings.html');
    }
    // 令牌就绪后加载配置
    setTimeout(loadConfig, 200);
  }

  function clearServerToken() {
    API.setToken('');
    toast('服务令牌已清除', 'success');
    loadServerToken();
  }

  // === 预设后端 ===
  function applyPreset(base, model) {
    $('cfg-llm_base_url').value = base;
    $('cfg-llm_model').value = model;
    toast(`已填入预设：${model}`, 'success');
    $('cfg-llm_api_key').focus();
  }

  // === 密码/令牌字段显隐切换（password-toggle） ===
  function initPasswordToggles() {
    document.querySelectorAll('.pw-toggle').forEach(btn => {
      btn.addEventListener('click', () => {
        const targetId = btn.getAttribute('data-toggle-target');
        const input = document.getElementById(targetId);
        if (!input) return;
        const show = input.type === 'password';
        input.type = show ? 'text' : 'password';
        const eye = btn.querySelector('.icon-eye');
        const eyeOff = btn.querySelector('.icon-eye-off');
        if (eye && eyeOff) {
          eye.style.display = show ? 'none' : 'block';
          eyeOff.style.display = show ? 'block' : 'none';
        }
        btn.setAttribute('aria-label', show ? '隐藏内容' : '显示内容');
        btn.setAttribute('aria-pressed', show ? 'true' : 'false');
      });
    });
  }

  // === 初始化 ===
  document.addEventListener('DOMContentLoaded', () => {
    $('save-btn').addEventListener('click', saveConfig);
    $('save-token-btn').addEventListener('click', saveServerToken);
    $('clear-token-btn').addEventListener('click', clearServerToken);

    document.querySelectorAll('.preset-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const base = btn.getAttribute('data-base');
        const model = btn.getAttribute('data-model');
        applyPreset(base, model);
      });
    });

    initPasswordToggles();

    // 先加载令牌状态，再按需加载配置（无令牌时不触发 401）
    loadServerToken();
    const authRedirect = location.search.includes('auth=1');
    if (API.hasToken()) {
      loadConfig();
    } else if (authRedirect) {
      // 从 401 跳转过来，高亮令牌区
      $('auth-section').scrollIntoView({ behavior: 'smooth' });
      toast('请先填写服务令牌', 'error');
    } else {
      // 首次访问无令牌，温和提示
      toast('请先在顶部填写服务令牌', '');
    }
  });
})();
