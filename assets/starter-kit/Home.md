# 🏠 驾驶舱

> 卡片式单页（Dataview JS 自绘，亮暗主题自适应）——卡片里的任务复选框**可直接勾选**（Dataview 回写源文件）；无 Dataview 时看下方「降级视图」

```dataviewjs
// ── Home 驾驶舱 · 卡片式单页自绘 ─────────────────────────────────
// 视觉布局层：数据口径与 Overview 一致（一次全库扫描＋按项目文件夹归集），不另立事实源。
// 交互：项目任务的复选框可勾选 → Dataview 自动回写源项目待办文件；
//       AI 待办卡片为**只读列表**（AI 日志的销项有「就地 ✅ 完成日」格式铁律，勾选会破坏格式，故不渲染复选框）。
// 降级：无 Dataview JS 时本块不渲染——下方 markdown 底座（入口＋周期按钮）仍可用。
const TODAY = dv.date('today');
const WEEK = TODAY.plus({ days: 7 });

// ① 样式注入（Obsidian 原生 CSS 变量——跟随主题；单文件自包含、零外部 CSS）
const styleEl = dv.el('style', '');
styleEl.textContent = `
.lm-dash{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:2px 0}
.lm-dash .lm-card{background:var(--background-secondary);border:1px solid var(--background-modifier-border);border-radius:12px;padding:10px 14px;min-width:0}
.lm-dash .lm-span2{grid-column:1/-1}
.lm-dash h4{margin:0 0 8px;font-size:.92em;color:var(--text-muted);font-weight:600}
.lm-banner{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.lm-badge{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:999px;background:var(--background-primary);border:1px solid var(--background-modifier-border);font-size:.88em}
.lm-red{color:#e05561}.lm-amber{color:#d99000}.lm-green{color:#4aa564}
.lm-tbl{width:100%;border-collapse:collapse;font-size:.9em}
.lm-tbl th{color:var(--text-muted);text-align:left;font-weight:500;padding:3px 8px;border-bottom:1px solid var(--background-modifier-border);white-space:nowrap}
.lm-tbl td{padding:4px 8px;border-bottom:1px solid var(--background-modifier-border)}
.lm-tbl tr:last-child td{border-bottom:none}
.lm-ul{list-style:none;margin:0;padding:0}
.lm-ul li{padding:4px 0;display:flex;justify-content:space-between;gap:8px;border-bottom:1px dashed var(--background-modifier-border)}
.lm-ul li:last-child{border-bottom:none}
.lm-muted{color:var(--text-muted);font-size:.85em;white-space:nowrap}
.lm-empty{color:var(--text-muted);font-size:.9em}
.lm-grp{margin:6px 0 2px;font-size:.88em;color:var(--text-muted)}
.lm-pills{display:flex;flex-wrap:wrap;gap:6px}
.lm-pill{display:inline-block;padding:3px 10px;border-radius:999px;background:var(--background-primary);border:1px solid var(--background-modifier-border);font-size:.88em}
@media (max-width:700px){.lm-dash{grid-template-columns:1fr}}
`;

// ② 一次全库扫描：项目桶（任务计数＋最新活跃）＋ AI 待办 ＋ 最近修改页
const projects = dv.pages('#Action/Project').where(p => p.状态 && p.状态 !== '已完成');
const projByFolder = new Map(projects.map(p => [p.file.folder, p]));
const stat = new Map();
for (const p of projects) stat.set(p.file.folder, { open: 0, overdue: 0, today: 0, soon: 0, latest: null, focusTasks: [] });

function ownerOf(path) {
  let folder = path.split('/').slice(0, -1).join('/');
  while (folder) {
    if (projByFolder.has(folder)) return projByFolder.get(folder);
    const i = folder.lastIndexOf('/');
    if (i < 0) break;
    folder = folder.slice(0, i);
  }
  return null;
}

let aiOpen = 0;
const aiTasks = [];
const recent = [];
for (const page of dv.pages()) {
  recent.push(page);
  const proj = ownerOf(page.file.path);
  if (!proj) {
    // AI 待办（只读）：04 AI Work/工作日志 下未完成顶层任务（回流机制保证其必在当月文件）
    if (page.file.path.startsWith('04 AI Work/工作日志/'))
      for (const t of page.file.tasks)
        if (!t.completed && !t.parent) { aiOpen++; aiTasks.push(t); }
    continue;
  }
  const s = stat.get(proj.file.folder);
  if (!s.latest || page.file.mtime > s.latest) s.latest = page.file.mtime;
  for (const t of page.file.tasks) {
    if (t.completed || t.parent) continue;
    s.open++;
    if (t.due) {
      const c = dv.compare(t.due, TODAY);
      if (c < 0) { s.overdue++; s.focusTasks.push(t); }
      else if (c === 0) { s.today++; s.focusTasks.push(t); }
      else if (dv.compare(t.due, WEEK) <= 0) s.soon++;
    }
  }
}

// ③ 健康度行（🔴 有逾期（任务或项目截止已过）／🟡 7 天内到期／🟢 平稳；🔴 优先）
const rows = projects.map(p => {
  const s = stat.get(p.file.folder);
  const due = p.截止日期 ? dv.date(p.截止日期) : null;
  const dueOver = due && dv.compare(due, TODAY) < 0;
  const dueSoon = due && !dueOver && dv.compare(due, WEEK) <= 0;
  const health = (s.overdue > 0 || dueOver) ? '🔴' : ((s.soon > 0 || dueSoon) ? '🟡' : '🟢');
  return { health, rank: health === '🔴' ? 0 : (health === '🟡' ? 1 : 2),
    p, s, due };
});
const cmpDue = (a, b) => {
  if (!a.due && !b.due) return 0;
  if (!a.due) return 1;
  if (!b.due) return -1;
  return dv.compare(a.due, b.due);
};
rows.sort((a, b) => a.rank - b.rank || cmpDue(a, b));

const totals = { overdue: 0, today: 0, open: 0 };
for (const r of rows) { totals.overdue += r.s.overdue; totals.today += r.s.today; totals.open += r.s.open; }

// ④ 最近动态（排除驾驶舱自身／模板／资料区；取 6 条）
const recentFiles = recent
  .filter(p => p.file.path !== dv.current().file.path
    && !p.file.path.includes('04 模板/')
    && !p.file.path.startsWith('01 资料/'))
  .sort((a, b) => dv.compare(b.file.mtime, a.file.mtime))
  .slice(0, 6);

function rel(dt) {
  const mins = Math.floor((Date.now() - dt.ts) / 60000);
  if (mins < 1) return '刚刚';
  if (mins < 60) return mins + ' 分钟前';
  const h = Math.floor(mins / 60);
  if (h < 24) return h + ' 小时前';
  return Math.floor(h / 24) + ' 天前';
}

function internalLink(path, text) {
  const a = document.createElement('a');
  a.className = 'internal-link';
  a.dataset.href = path;
  a.textContent = text;
  return a;
}

// 任务列表渲染进指定卡片（保住勾选回写交互）：临时切换 dv.container
function taskListInto(el, tasks) {
  if (!tasks.length) {
    const e = document.createElement('div'); e.className = 'lm-empty';
    e.textContent = '✅ 无'; el.appendChild(e); return;
  }
  const holder = document.createElement('div');
  el.appendChild(holder);
  const prev = dv.container;
  dv.container = holder;
  try { dv.taskList(tasks, false); } finally { dv.container = prev; }
}

// ⑤ 布局渲染：横幅 ＋ 卡片 grid
const root = dv.el('div', '');
root.className = 'lm-dash';

// 横幅（跨两列）：日期 ＋ 统计徽章
const banner = document.createElement('div');
banner.className = 'lm-card lm-span2 lm-banner';
banner.innerHTML = `📅 <b>${TODAY.toFormat('yyyy-MM-dd')}</b>`;
const mkBadge = (html, cls) => {
  const b = document.createElement('span');
  b.className = 'lm-badge ' + (cls || '');
  b.innerHTML = html;
  return b;
};
banner.appendChild(mkBadge(`🏗 进行中／待开始 <b>${rows.length}</b>`));
banner.appendChild(mkBadge(`⚠️ 逾期 <b>${totals.overdue}</b>`, totals.overdue ? 'lm-red' : ''));
banner.appendChild(mkBadge(`📅 今日到期 <b>${totals.today}</b>`));
banner.appendChild(mkBadge(`📋 未完成任务 <b>${totals.open}</b>`));
banner.appendChild(mkBadge(`🤖 AI 待办 <b>${aiOpen}</b>`));
root.appendChild(banner);

// 卡片：项目健康度（跨两列）
const cardHealth = document.createElement('div');
cardHealth.className = 'lm-card lm-span2';
cardHealth.innerHTML = '<h4>🏥 项目健康度</h4>';
if (rows.length === 0) {
  const e = document.createElement('div'); e.className = 'lm-empty'; e.textContent = '📭 暂无进行中／待开始项目';
  cardHealth.appendChild(e);
} else {
  const tbl = document.createElement('table'); tbl.className = 'lm-tbl';
  const thead = document.createElement('tr');
  for (const h of ['健康', '项目', '状态', '截止', '⚠️逾期', '未完成', '最后活跃']) {
    const th = document.createElement('th'); th.textContent = h; thead.appendChild(th);
  }
  tbl.appendChild(thead);
  for (const r of rows) {
    const tr = document.createElement('tr');
    const cells = [
      { text: r.health },
      { link: true },
      { text: r.p.状态 ?? '—' },
      { text: r.due ? r.due.toFormat('yyyy-MM-dd') : '—' },
      { text: String(r.s.overdue), red: r.s.overdue > 0, bold: r.s.overdue > 0 },
      { text: String(r.s.open) },
      { text: r.s.latest ? r.s.latest.toFormat('yyyy-MM-dd') : '—' },
    ];
    for (const c of cells) {
      const td = document.createElement('td');
      if (c.link) td.appendChild(internalLink(r.p.file.path, r.p.file.name));
      else td.textContent = c.text;
      if (c.red) td.classList.add('lm-red');
      if (c.bold) td.style.fontWeight = '700';
      tr.appendChild(td);
    }
    tbl.appendChild(tr);
  }
  cardHealth.appendChild(tbl);
}
root.appendChild(cardHealth);

// 卡片：今日焦点（逾期＋今日到期，按项目分组；可勾选）
const cardFocus = document.createElement('div');
cardFocus.className = 'lm-card';
cardFocus.innerHTML = '<h4>⚠️ 今日焦点（逾期 ＋ 今日到期）</h4>';
const focusGroups = rows.filter(r => r.s.focusTasks.length > 0);
if (!focusGroups.length) {
  const e = document.createElement('div'); e.className = 'lm-empty'; e.textContent = '✅ 无逾期、无今日到期——清爽';
  cardFocus.appendChild(e);
} else {
  for (const r of focusGroups) {
    const g = document.createElement('div');
    const t = document.createElement('div'); t.className = 'lm-grp';
    t.appendChild(internalLink(r.p.file.path, '🏷 ' + r.p.file.name));
    g.appendChild(t);
    taskListInto(g, r.s.focusTasks);
    cardFocus.appendChild(g);
  }
}
root.appendChild(cardFocus);

// 卡片：AI 待办（只读列表——AI 日志销项有 ✅ 完成日格式铁律，不做勾选）
const cardAI = document.createElement('div');
cardAI.className = 'lm-card';
cardAI.innerHTML = `<h4>🤖 AI 待办（${aiOpen}）</h4>`;
if (!aiTasks.length) {
  const e = document.createElement('div'); e.className = 'lm-empty'; e.textContent = '✅ AI 无未完成事项';
  cardAI.appendChild(e);
} else {
  const ul = document.createElement('ul'); ul.className = 'lm-ul';
  for (const t of aiTasks) {
    const li = document.createElement('li');
    const span = document.createElement('span');
    span.textContent = (t.text || '').replace(/#[^\s#]+/g, '').trim() || '(无标题)';
    li.appendChild(span);
    ul.appendChild(li);
  }
  cardAI.appendChild(ul);
  const tip = document.createElement('div'); tip.className = 'lm-muted';
  tip.textContent = '销项请走 AI 会话（就地 ✅ 完成日）';
  cardAI.appendChild(tip);
}
root.appendChild(cardAI);

// 卡片：最近动态
const cardRecent = document.createElement('div');
cardRecent.className = 'lm-card';
cardRecent.innerHTML = '<h4>🕐 最近动态</h4>';
if (!recentFiles.length) {
  const e = document.createElement('div'); e.className = 'lm-empty'; e.textContent = '（暂无）';
  cardRecent.appendChild(e);
} else {
  const ul = document.createElement('ul'); ul.className = 'lm-ul';
  for (const p of recentFiles) {
    const li = document.createElement('li');
    li.appendChild(internalLink(p.file.path, p.file.name));
    const m = document.createElement('span'); m.className = 'lm-muted'; m.textContent = rel(p.file.mtime);
    li.appendChild(m);
    ul.appendChild(li);
  }
  cardRecent.appendChild(ul);
}
root.appendChild(cardRecent);

// 卡片：快速入口
const cardNav = document.createElement('div');
cardNav.className = 'lm-card';
cardNav.innerHTML = '<h4>📌 快速入口</h4>';
const pills = document.createElement('div'); pills.className = 'lm-pills';
const navItems = [
  ['Overview', '总览·任务明细'],
  ['02 工作', '工作'],
  ['01 任务', '任务'],
  ['02 工作/02 项目/项目看板', '项目看板'],
  ['04 AI Work/待办事项', 'AI 待办看板'],
];
for (const [path, text] of navItems) {
  const a = internalLink(path, text);
  a.className = 'lm-pill internal-link';
  pills.appendChild(a);
}
cardNav.appendChild(pills);
root.appendChild(cardNav);
```

## 降级视图

- [[Overview|总览——逾期／近 7 天／未排期任务明细]]
- [[02 工作|工作]] ｜ [[01 任务|任务]] ｜ [[02 项目|项目]] ｜ [[02 工作/02 项目/项目看板|项目看板]] ｜ [[04 AI Work/待办事项|AI 待办事项]]

## 周期总览

```button
name 📅 今日日报
type command
action Periodic Notes: Open daily note
color blue
```

```button
name 📆 本周周报
type command
action Periodic Notes: Open weekly note
color green
```

```button
name 🗓️ 本月月报
type command
action Periodic Notes: Open monthly note
color orange
```
