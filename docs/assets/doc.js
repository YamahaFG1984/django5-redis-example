// Django5 × Redis 教学文档 —— 公共脚本：主题切换 / 目录生成 / Mermaid / 代码高亮
(function () {
  var KEY = 'redis-docs-theme';
  var saved = null;
  try { saved = localStorage.getItem(KEY); } catch (e) {}
  if (saved) document.documentElement.setAttribute('data-theme', saved);

  function isDark() {
    var t = document.documentElement.getAttribute('data-theme');
    if (t) return t === 'dark';
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  }

  document.addEventListener('DOMContentLoaded', function () {
    // 主题按钮：切换后刷新，让 Mermaid 用新主题重新渲染
    var btn = document.querySelector('.theme-btn');
    if (btn) {
      btn.textContent = isDark() ? '☀ 浅色' : '☾ 深色';
      btn.addEventListener('click', function () {
        var next = isDark() ? 'light' : 'dark';
        try { localStorage.setItem(KEY, next); } catch (e) {}
        location.reload();
      });
    }

    // 根据 h2/h3 自动生成左侧目录
    var toc = document.querySelector('.toc');
    if (toc) {
      var heads = document.querySelectorAll('main h2[id], main h3[id]');
      var html = '<div class="toc-title">本页目录</div>';
      heads.forEach(function (h) {
        var num = h.querySelector('.num');
        var text = num ? num.textContent + '. ' + h.textContent.slice(num.textContent.length) : h.textContent;
        html += '<a class="' + h.tagName.toLowerCase() + '" href="#' + h.id + '">' + text + '</a>';
      });
      toc.innerHTML = html;
      var links = toc.querySelectorAll('a');
      if ('IntersectionObserver' in window) {
        var obs = new IntersectionObserver(function (entries) {
          entries.forEach(function (en) {
            if (en.isIntersecting) {
              links.forEach(function (a) { a.classList.toggle('active', a.getAttribute('href') === '#' + en.target.id); });
            }
          });
        }, { rootMargin: '-80px 0px -70% 0px' });
        heads.forEach(function (h) { obs.observe(h); });
      }
    }

    if (window.hljs) {
      document.querySelectorAll('pre code[class*="language-"]').forEach(function (el) { window.hljs.highlightElement(el); });
    }

    if (window.mermaid) {
      window.mermaid.initialize({
        startOnLoad: false,
        theme: isDark() ? 'dark' : 'neutral',
        securityLevel: 'loose',
        fontFamily: '"Noto Sans SC", sans-serif',
        sequence: { mirrorActors: false, showSequenceNumbers: true },
        flowchart: { curve: 'basis' }
      });
      // 等网络字体加载完再渲染：否则 Mermaid 按后备字体测量文字宽度，节点里的中文会被截断
      var ready = document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve();
      ready.then(function () { window.mermaid.run({ querySelector: '.mermaid' }); });
    }
  });
})();
