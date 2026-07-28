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
    btn.innerHTML = '<span class="text-sm">保存中...</span>';

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

  // === 预设后端 ===
  function applyPreset(base, model) {
    $('cfg-llm_base_url').value = base;
    $('cfg-llm_model').value = model;
    toast(`已填入预设：${model}`, 'success');
    $('cfg-llm_api_key').focus();
  }

  // === 初始化 ===
  document.addEventListener('DOMContentLoaded', () => {
    $('save-btn').addEventListener('click', saveConfig);

    document.querySelectorAll('.preset-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const base = btn.getAttribute('data-base');
        const model = btn.getAttribute('data-model');
        applyPreset(base, model);
      });
    });

    loadConfig();
  });
})();
