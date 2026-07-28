// === 暗色模式切换与持久化 ===
// 配合各页面 <head> 内联的防 FOUC 引导脚本使用。
// 主题存储于 localStorage（key: pga_theme），值为 'light' | 'dark'。
// 首次访问跟随系统偏好 prefers-color-scheme。

const Theme = (() => {
  const KEY = 'pga_theme';

  function current() {
    return document.documentElement.getAttribute('data-theme') || 'light';
  }

  function apply(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    try { localStorage.setItem(KEY, theme); } catch (e) { /* ignore */ }
    updateToggleUI(theme);
  }

  function toggle() {
    apply(current() === 'dark' ? 'light' : 'dark');
  }

  // 更新切换按钮的图标与 aria-label（nav-state-active / 可访问标签）
  function updateToggleUI(theme) {
    document.querySelectorAll('[data-theme-toggle]').forEach(btn => {
      btn.setAttribute('aria-label', theme === 'dark' ? '切换到亮色模式' : '切换到暗色模式');
      btn.setAttribute('title', theme === 'dark' ? '亮色模式' : '暗色模式');
      const sun = btn.querySelector('.icon-sun');
      const moon = btn.querySelector('.icon-moon');
      if (sun && moon) {
        sun.style.display = theme === 'dark' ? 'block' : 'none';
        moon.style.display = theme === 'dark' ? 'none' : 'block';
      }
    });
  }

  function init() {
    const stored = (() => { try { return localStorage.getItem(KEY); } catch (e) { return null; } })();
    const theme = stored || (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    document.documentElement.setAttribute('data-theme', theme);
    updateToggleUI(theme);

    document.querySelectorAll('[data-theme-toggle]').forEach(btn => {
      btn.addEventListener('click', toggle);
    });

    // 跟随系统变化（仅当用户未显式选择时）
    if (!stored && window.matchMedia) {
      window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
        if (!localStorage.getItem(KEY)) {
          document.documentElement.setAttribute('data-theme', e.matches ? 'dark' : 'light');
          updateToggleUI(e.matches ? 'dark' : 'light');
        }
      });
    }
  }

  return { init, toggle, current, apply };
})();

document.addEventListener('DOMContentLoaded', Theme.init);
