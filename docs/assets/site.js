/* ================================================================
   Django × Redis 实战 · 共享脚本：侧边栏、目录、代码高亮、主题
   （结构沿用 Hono 教程的 site.js）
   ================================================================ */
// 保持经典 <script> 而不是 type="module"：模块脚本在 file:// 下会被浏览器拦截，
// 而这些页面经常是直接双击打开的。
(() => {
  'use strict';

  // 页面分布在 docs/ 和 docs/features/ 两层目录里，链接统一相对于 docs/ 计算
  const BASE = (document.currentScript?.src || '').replace(/assets\/site\.js(\?.*)?$/, '');

  const CHAPTERS = [
    { key: 'prd',    n: 'A',  t: '产品需求文档',     d: '用户角色、功能清单、用户故事与验收标准', href: '01-prd.html', tag: 'step-01-docs', part: '第一部分 · 需求与设计' },
    { key: 'design', n: 'B',  t: '系统设计',         d: '架构、分层、Key 规范、一致性策略', href: '02-design.html', tag: 'step-01-docs' },
    { key: '02', n: '02', t: '接入 Redis',          d: '连接池、Key 规范、测试基类、演示数据', href: 'features/02-redis-setup.html', tag: 'step-02-redis-setup', types: ['string'], part: '第二部分 · 计数与缓存' },
    { key: '03', n: '03', t: '文章浏览量 PV / UV',   d: '原子计数、防刷去重、HyperLogLog、回写数据库', href: 'features/03-page-views.html', tag: 'step-03-page-views', types: ['string', 'hll', 'set'] },
    { key: '04', n: '04', t: '热门排行榜',          d: '总榜、日榜、周榜与 ZUNIONSTORE', href: 'features/04-hot-ranking.html', tag: 'step-04-hot-ranking', types: ['zset'] },
    { key: '05', n: '05', t: '页面与查询缓存',      d: 'Cache-Aside、穿透 / 击穿 / 雪崩、分布式锁', href: 'features/05-cache.html', tag: 'step-05-cache', types: ['string', 'lua'] },
    { key: '06', n: '06', t: '点赞',               d: '幂等点赞、双向索引、ZMSCORE 批量判断', href: 'features/06-likes.html', tag: 'step-06-likes', types: ['set', 'zset'], part: '第三部分 · 用户互动' },
    { key: '07', n: '07', t: '每日签到',            d: 'Bitmap 日历、BITFIELD、BITOP 与 Hash 统计', href: 'features/07-checkin.html', tag: 'step-07-checkin', types: ['bitmap', 'hash'] },
    { key: '08', n: '08', t: '关注与时间线',        d: '写扩散 Feed 流、游标分页、共同关注', href: 'features/08-timeline.html', tag: 'step-08-follow-timeline', types: ['set', 'zset'] },
    { key: '09', n: '09', t: '个性化推荐',          d: '兴趣画像、标签倒排、加权并集', href: 'features/09-recommend.html', tag: 'step-09-recommend', types: ['zset', 'set'], part: '第四部分 · 发现与防护' },
    { key: '10', n: '10', t: '接口限流',            d: '固定窗口、滑动窗口与 Lua 原子性', href: 'features/10-rate-limit.html', tag: 'step-10-rate-limit', types: ['string', 'zset', 'lua'] },
    { key: '11', n: '11', t: '热搜、历史与联想',     d: 'ZINCRBY、LTRIM、ZRANGEBYLEX', href: 'features/11-search.html', tag: 'step-11-search', types: ['zset', 'list'] },
    { key: '12', n: '12', t: '评论通知',            d: 'Stream 消费组、ACK 与崩溃恢复', href: 'features/12-notifications.html', tag: 'step-12-notifications', types: ['stream', 'list', 'string'], part: '第五部分 · 异步任务' }
  ];
  const TYPE_NAMES = { string: 'STRING', hash: 'HASH', list: 'LIST', set: 'SET', zset: 'ZSET', bitmap: 'BITMAP', hll: 'HLL', stream: 'STREAM', lua: 'LUA' };

  const url = (href) => BASE + href;
  const curKey = document.body.dataset.page || '';
  const curIdx = CHAPTERS.findIndex((c) => c.key === curKey);

  /* ---------- 侧边栏 ---------- */
  const side = document.getElementById('sidebar');
  if (side) {
    const brand = `<a class="brand" href="${url('index.html')}"><span class="flame">R</span>` +
      '<span>Django × Redis 实战<small>用一个博客学会 Redis</small></span></a>';
    const links = CHAPTERS.map(({ key, n, t, href, part }) =>
      (part ? `<div class="part">${part}</div>` : '') +
      `<a class="ch${key === curKey ? ' active' : ''}" href="${url(href)}"><span class="n">${n}</span><span>${t}</span></a>`
    );
    side.innerHTML = brand + links.join('');
    const active = side.querySelector('a.ch.active');
    if (active) setTimeout(() => active.scrollIntoView({ block: 'center' }), 0);
  }

  /* ---------- 移动端菜单 ---------- */
  const btn = Object.assign(document.createElement('button'), {
    id: 'menu-btn',
    type: 'button',
    innerHTML: '&#9776;',
    onclick: () => document.body.classList.toggle('nav-open')
  });
  btn.setAttribute('aria-label', '目录');
  document.body.appendChild(btn);
  document.addEventListener('click', (e) => {
    if (document.body.classList.contains('nav-open') &&
        side && !side.contains(e.target) && e.target !== btn) {
      document.body.classList.remove('nav-open');
    }
  });

  /* ---------- 主题切换 ---------- */
  const THEME_KEY = 'redis-docs-theme';
  const tbtn = Object.assign(document.createElement('button'), {
    id: 'theme-btn',
    type: 'button',
    innerHTML: '&#9789;',
    onclick: () => {
      const root = document.documentElement;
      const now = root.getAttribute('data-theme');
      const dark = now ? now === 'dark'
        : window.matchMedia('(prefers-color-scheme: dark)').matches;
      const next = dark ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      try { localStorage.setItem(THEME_KEY, next); } catch {}
    }
  });
  tbtn.setAttribute('aria-label', '切换深浅色');
  document.body.appendChild(tbtn);
  try {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved) document.documentElement.setAttribute('data-theme', saved);
  } catch {}

  /* ---------- 箭头 marker（全局一次） ---------- */
  const defs = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  defs.setAttribute('width', '0');
  defs.setAttribute('height', '0');
  defs.setAttribute('style', 'position:absolute');
  // 注意：SVG marker 的内容不会从引用它的元素继承 color，
  // 所以这里直接用 CSS 变量填色，而不是 currentColor。
  const marker = (id, fill) =>
    `<marker id="${id}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">` +
    `<path d="M0,0 L10,5 L0,10 z" fill="${fill}"/></marker>`;
  defs.innerHTML = '<defs>' +
    marker('ar', 'var(--fg-faint)') + marker('ar-a', 'var(--accent)') +
    marker('ar-b', 'var(--blue)') + marker('ar-g', 'var(--green)') +
    marker('ar-r', 'var(--red)') + marker('ar-p', 'var(--purple)') +
    marker('ar-t', 'var(--teal)') + marker('ar-y', 'var(--gold)') +
    '</defs>';
  document.body.appendChild(defs);

  /* ---------- 章节内目录 ---------- */
  const main = document.querySelector('main');
  const slot = document.getElementById('chapter-toc');
  if (slot && main) {
    const hs = [...main.querySelectorAll('h2')];
    if (hs.length > 2) {
      const items = hs.map((h, i) => {
        if (!h.id) h.id = `sec-${i + 1}`;
        return `<li><a href="#${h.id}">${h.textContent}</a></li>`;
      });
      slot.className = 'toc';
      slot.innerHTML = `<div class="h">本章目录</div><ol>${items.join('')}</ol>`;
    }
  }

  /* ---------- 代码块：语言标签 + 复制 + 高亮 ---------- */
  const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  function paint(src, re, classes) {
    let out = '';
    let last = 0;
    // 所有分支都至少匹配一个字符，matchAll 不会卡在零宽匹配上
    for (const m of src.matchAll(re)) {
      out += esc(src.slice(last, m.index));
      const g = m.findIndex((v, i) => i > 0 && v !== undefined);
      out += `<span class="${classes[g - 1]}">${esc(m[g])}</span>`;
      last = m.index + m[0].length;
    }
    return out + esc(src.slice(last));
  }

  // 每一段用正则字面量写，取 .source 拼起来，省掉字符串里的双重转义
  const join = (parts, flags = 'g') => new RegExp(parts.map((p) => (p instanceof RegExp ? p.source : p)).join('|'), flags);
  const words = (list) => String.raw`\b(${list})\b`;

  const PY_KW = 'False|None|True|and|as|assert|async|await|break|class|continue|def|del|elif|else|except|' +
    'finally|for|from|global|if|import|in|is|lambda|nonlocal|not|or|pass|raise|return|try|while|with|yield|self';
  const LUA_KW = 'local|if|then|else|elseif|end|return|function|and|or|not|nil|true|false|for|in|do|while';
  const SQL_KW = 'SELECT|FROM|WHERE|AND|OR|IN|ORDER|BY|DESC|ASC|LIMIT|OFFSET|GROUP|UPDATE|SET|INSERT|INTO|' +
    'VALUES|DELETE|JOIN|ON|AS|COUNT|LIKE|NOT|NULL';

  const STR = /("""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')/;
  const RULES = {
    python: [join([/(#[^\n]*)/, /((?:\b[rRbBfF]{1,2})?(?:"""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'))/,
      words(PY_KW), /(@[\w.]+)/, /\b([A-Z][A-Za-z0-9_]*)\b/, /\b(\d[\d_]*(?:\.\d+)?)\b/, /\b([a-zA-Z_]\w*)(?=\()/]),
      ['tk-cm', 'tk-st', 'tk-kw', 'tk-tp', 'tk-tp', 'tk-nm', 'tk-fn']],
    lua: [join([/(--[^\n]*)/, STR, words(LUA_KW), /\b(\d+)\b/, /\b([a-zA-Z_][\w.]*)(?=\()/]),
      ['tk-cm', 'tk-st', 'tk-kw', 'tk-nm', 'tk-fn']],
    yaml: [join([/(#[^\n]*)/, STR, /^(\s*[\w.-]+)(?=:)/m, /\b(\d+)\b/], 'gm'),
      ['tk-cm', 'tk-st', 'tk-kw', 'tk-nm']],
    sql: [join([/(--[^\n]*)/, STR, words(SQL_KW), /\b(\d+)\b/]),
      ['tk-cm', 'tk-st', 'tk-kw', 'tk-nm']],
    html: [join([/(<!--[\s\S]*?-->|\{#[\s\S]*?#\})/, /(\{%[\s\S]*?%\}|\{\{[\s\S]*?\}\})/, /("[^"\n]*")/, /(<\/?[a-zA-Z][\w-]*|\/?>)/]),
      ['tk-cm', 'tk-kw', 'tk-st', 'tk-fn']],
    bash: [/(#[^\n]*)|('(?:\\[\s\S]|[^\\'])*'|"(?:\\[\s\S]|[^\\"])*")|\b(pip|python|python3|git|cd|docker|export|curl|manage\.py)\b/g,
      ['tk-cm', 'tk-st', 'tk-kw']]
  };

  // redis-cli / shell 会话：带提示符的是命令，其余是输出
  const PROMPT = /^(\$ |> |>>> |127\.0\.0\.1:6379> )/;
  function paintCli(src) {
    return src.split('\n').map((line) => {
      if (/^\s*#/.test(line)) return `<span class="tk-cm">${esc(line)}</span>`;
      const m = line.match(PROMPT);
      if (!m) return line ? `<span class="tk-out">${esc(line)}</span>` : '';
      let rest = line.slice(m[0].length);
      let comment = '';
      const c = rest.search(/\s{2,}#/);
      if (c >= 0) { comment = rest.slice(c); rest = rest.slice(0, c); }
      const [, cmd, args] = rest.match(/^(\S*)([\s\S]*)$/);
      return `<span class="tk-pr">${esc(m[0])}</span><span class="tk-kw">${esc(cmd)}</span>` +
        paint(args, /('(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*")/g, ['tk-st']) +
        (comment ? `<span class="tk-cm">${esc(comment)}</span>` : '');
    }).join('\n');
  }
  function paintDiff(src) {
    return src.split('\n').map((line) => {
      if (line.startsWith('+')) return `<span class="tk-add">${esc(line)}</span>`;
      if (line.startsWith('-')) return `<span class="tk-del">${esc(line)}</span>`;
      return paint(line, RULES.python[0], RULES.python[1]);
    }).join('\n');
  }

  const LANG_LABEL = { cli: 'terminal', text: 'text' };
  document.querySelectorAll('.code').forEach((box) => {
    const pre = box.querySelector('pre');
    if (!pre) return;
    const { lang = 'text', file = '' } = box.dataset;

    const bar = document.createElement('div');
    bar.className = 'bar';
    bar.innerHTML = `<span class="tag">${esc(file || LANG_LABEL[lang] || lang)}</span>`;
    const cp = Object.assign(document.createElement('button'), {
      className: 'copy',
      type: 'button',
      textContent: '复制'
    });
    cp.onclick = () => {
      // 终端会话只复制命令，不复制提示符和输出
      const text = lang === 'cli'
        ? pre.textContent.split('\n').filter((l) => PROMPT.test(l)).map((l) => l.replace(PROMPT, '').replace(/\s{2,}#.*$/, '')).join('\n')
        : pre.textContent;
      navigator.clipboard?.writeText(text);
      cp.textContent = '已复制';
      setTimeout(() => { cp.textContent = '复制'; }, 1400);
    };
    bar.appendChild(cp);
    box.insertBefore(bar, pre);

    const code = pre.textContent.replace(/^\n/, '').replace(/\s+$/, '');
    if (lang === 'cli') pre.innerHTML = paintCli(code);
    else if (lang === 'diff') pre.innerHTML = paintDiff(code);
    else if (RULES[lang]) pre.innerHTML = paint(code, ...RULES[lang]);
    else pre.textContent = code;
  });

  /* ---------- 上一章 / 下一章 ---------- */
  const pager = document.getElementById('pager');
  if (pager && curIdx >= 0) {
    const prev = CHAPTERS[curIdx - 1];
    const next = CHAPTERS[curIdx + 1];
    const label = (c) => (/^\d+$/.test(c.n) ? `Step ${c.n} · ${c.t}` : c.t);
    const prevLink = prev
      ? `<a class="prev" href="${url(prev.href)}"><span>&larr; 上一章</span>${label(prev)}</a>`
      : `<a class="prev" href="${url('index.html')}"><span>&larr; 返回</span>课程首页</a>`;
    const nextLink = next
      ? `<a class="next" href="${url(next.href)}"><span>下一章 &rarr;</span>${label(next)}</a>`
      : `<a class="next" href="${url('index.html')}"><span>完成 &rarr;</span>回到课程首页</a>`;
    pager.className = 'pager';
    pager.innerHTML = prevLink + nextLink;
  }

  /* ---------- 首页目录 ---------- */
  const grid = document.getElementById('toc-grid');
  if (grid) {
    grid.className = 'toc-grid';
    grid.innerHTML = CHAPTERS.map(({ n, t, d, href, tag, types = [] }) =>
      `<a class="toc-card" href="${url(href)}">` +
      `<div class="n">${/^\d+$/.test(n) ? `STEP ${n}` : '设计文档'}</div>` +
      `<div class="t">${t}</div>` +
      `<div class="d">${d}</div>` +
      `<div class="tg">${tag}</div>` +
      (types.length ? `<div class="ty">${types.map((k) => `<span class="rt ${k}">${TYPE_NAMES[k]}</span>`).join('')}</div>` : '') +
      '</a>'
    ).join('');
  }
})();
