// ── Palette (colorblind-safe categorical) ─────────────────────────────────────

const PALETTE = [
  { hex: '#0ea5e9', rgb: '14,165,233'  }, // sky
  { hex: '#10b981', rgb: '16,185,129'  }, // emerald
  { hex: '#8b5cf6', rgb: '139,92,246'  }, // violet
  { hex: '#f59e0b', rgb: '245,158,11'  }, // amber
  { hex: '#ef4444', rgb: '239,68,68'   }, // red
  { hex: '#ec4899', rgb: '236,72,153'  }, // pink
  { hex: '#6366f1', rgb: '99,102,241'  }, // indigo
  { hex: '#14b8a6', rgb: '20,184,166'  }, // teal
];

// ── State ─────────────────────────────────────────────────────────────────────

const state = {
  graph:      null,
  view:       'overview', // 'overview' | 'need'
  activeNeed: null,
  selectedId: null,
  needColors: new Map(), // needId -> { hex, rgb }
};

let sharedIds   = new Set();
let openPopover = null;

// ── DOM refs ──────────────────────────────────────────────────────────────────

const stageEl       = document.querySelector('#stage');
const drawerEl      = document.querySelector('#detail-drawer');
const searchOverlay = document.querySelector('#search-overlay');
const searchInput   = document.querySelector('#search-input');
const searchResults = document.querySelector('#search-results');
const overflowMenu  = document.querySelector('#overflow-menu');
const toastEl       = document.querySelector('#toast-container');

// ── API ───────────────────────────────────────────────────────────────────────

async function loadGraph() {
  try {
    const res = await fetch('/api/graph');
    if (!res.ok) throw new Error(await res.text());
    state.graph = await res.json();
    state.graph.hierarchy.forEach((need, i) => {
      state.needColors.set(need.id, PALETTE[i % PALETTE.length]);
    });
    sharedIds = buildSharedIds(state.graph.hierarchy);
    renderOverview();
  } catch {
    showCanvasMessage('Could not load graph. Import seed data and check Neo4j credentials.');
  }
}

async function postGraphAction(path) {
  const res = await fetch(path, { method: 'POST' });
  const body = await res.json();
  if (!res.ok) throw new Error(body.error || res.statusText);
  return body;
}

async function loadJson() {
  if (!confirm('Replace the Neo4j planning graph with data/financial-planning-graph.json?')) return;
  setBusy(true);
  try {
    const result = await postGraphAction('/api/graph/import');
    state.activeNeed = null;
    state.selectedId = null;
    state.needColors  = new Map();
    sharedIds = new Set();
    await loadGraph();
    showToast(`Loaded ${result.nodes} nodes and ${result.relationships} relationships.`);
  } catch (err) {
    showToast(err.message);
  } finally {
    setBusy(false);
  }
}

async function exportJson() {
  setBusy(true);
  try {
    const res = await fetch('/api/graph/export');
    const body = await res.json();
    if (!res.ok) throw new Error(body.error || res.statusText);
    downloadJson(body);
    showToast(`Exported ${body.nodes.length} nodes and ${body.relationships.length} relationships.`);
  } catch (err) {
    showToast(err.message);
  } finally {
    setBusy(false);
  }
}

async function wipeGraph() {
  if (!confirm('Delete all FinancialPlanningGraph nodes and relationships from Neo4j?')) return;
  setBusy(true);
  try {
    await postGraphAction('/api/graph/wipe');
    state.activeNeed = null;
    state.selectedId = null;
    state.needColors  = new Map();
    sharedIds = new Set();
    await loadGraph();
    showToast('Planning graph wiped.');
  } catch (err) {
    showToast(err.message);
  } finally {
    setBusy(false);
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function getType(node) {
  if (node.type)  return node.type;
  const labels = node.labels || [];
  if (labels.includes('Need'))    return 'Need';
  if (labels.includes('Subneed')) return 'Subneed';
  return 'Task';
}

function buildSharedIds(hierarchy) {
  const seen = new Set();
  const shared = new Set();
  function walk(nodes) {
    for (const n of nodes) {
      if (seen.has(n.id)) shared.add(n.id);
      else seen.add(n.id);
      walk(n.subneeds || []);
      walk(n.tasks    || []);
    }
  }
  walk(hierarchy);
  return shared;
}

function countTasks(node) {
  let n = (node.tasks || []).length;
  for (const s of (node.subneeds || [])) n += countTasks(s);
  return n;
}

function taskExistsUnder(node, taskId) {
  for (const t of (node.tasks    || [])) if (t.id === taskId) return true;
  for (const s of (node.subneeds || [])) if (taskExistsUnder(s, taskId)) return true;
  return false;
}

function getOtherNeedsForTask(taskId) {
  if (!state.graph) return [];
  return state.graph.hierarchy.filter(need => {
    if (need === state.activeNeed) return false;
    return taskExistsUnder(need, taskId);
  });
}

function getTaskHomes(taskId) {
  const homes = [];
  if (!state.graph) return homes;
  for (const need of state.graph.hierarchy) {
    for (const t of (need.tasks || [])) {
      if (t.id === taskId) homes.push({ needId: need.id, needName: need.name, subneedName: null });
    }
    for (const sub of (need.subneeds || [])) {
      for (const t of (sub.tasks || [])) {
        if (t.id === taskId) homes.push({ needId: need.id, needName: need.name, subneedName: sub.name });
      }
    }
  }
  return homes;
}

function prefersReducedMotion() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function setBusy(busy) {
  for (const btn of overflowMenu.querySelectorAll('button')) btn.disabled = busy;
}

function showToast(msg) {
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = msg;
  toastEl.appendChild(toast);
  setTimeout(() => toast.remove(), 4000);
}

function showCanvasMessage(msg) {
  stageEl.innerHTML = `<p class="canvas-empty">${msg}</p>`;
}

function downloadJson(value) {
  const blob = new Blob([JSON.stringify(value, null, 2) + '\n'], { type: 'application/json' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href = url; a.download = 'financial-planning-graph.json'; a.click();
  URL.revokeObjectURL(url);
}

function setAccent(el, needId) {
  const color = state.needColors.get(needId);
  if (!color) return;
  el.style.setProperty('--accent',     color.hex);
  el.style.setProperty('--accent-rgb', color.rgb);
}

// ── Tier 0: Overview ──────────────────────────────────────────────────────────

function renderOverview() {
  state.view = 'overview';
  state.activeNeed = null;
  closeDrawer();
  stageEl.innerHTML = '';

  if (!state.graph || !state.graph.hierarchy.length) {
    showCanvasMessage('No data. Load the seed JSON to get started.');
    return;
  }

  const grid = document.createElement('div');
  grid.className = 'concept-grid';
  for (const need of state.graph.hierarchy) {
    grid.appendChild(buildNeedCard(need));
  }
  stageEl.appendChild(grid);
}

function buildNeedCard(need) {
  const taskCount    = countTasks(need);
  const subneedCount = (need.subneeds || []).length;

  const card = document.createElement('div');
  card.className = 'need-card';
  setAccent(card, need.id);
  card.dataset.needId = need.id;

  const accent = document.createElement('div');
  accent.className = 'need-card-accent';
  card.appendChild(accent);

  const body = document.createElement('div');
  body.className = 'need-card-body';

  const name = document.createElement('h2');
  name.className = 'need-card-name';
  name.textContent = need.name;
  body.appendChild(name);

  if (need.description) {
    const desc = document.createElement('p');
    desc.className = 'need-card-desc';
    desc.textContent = need.description;
    body.appendChild(desc);
  }

  const meta = document.createElement('div');
  meta.className = 'need-card-meta';
  meta.textContent = `${subneedCount} subneed${subneedCount !== 1 ? 's' : ''} · ${taskCount} task${taskCount !== 1 ? 's' : ''}`;
  body.appendChild(meta);
  card.appendChild(body);

  const hoverList = document.createElement('div');
  hoverList.className = 'need-card-subneeds';
  for (const s of (need.subneeds || [])) {
    const item = document.createElement('div');
    item.className = 'need-card-subneed';
    item.textContent = s.name;
    hoverList.appendChild(item);
  }
  card.appendChild(hoverList);

  card.addEventListener('click', () => navigateToNeed(need, card));
  return card;
}

// ── Tier 1: Need focus ────────────────────────────────────────────────────────

function navigateToNeed(need, fromCard) {
  const fromRect = (fromCard && !prefersReducedMotion())
    ? fromCard.getBoundingClientRect()
    : null;

  state.view = 'need';
  state.activeNeed = need;
  stageEl.innerHTML = '';

  // Header band
  const header = document.createElement('div');
  header.className = 'board-header';
  setAccent(header, need.id);

  const nav = document.createElement('nav');
  nav.className = 'board-breadcrumb';

  const backBtn = document.createElement('button');
  backBtn.className = 'breadcrumb-back';
  backBtn.textContent = 'All needs';
  backBtn.addEventListener('click', navigateBack);

  const sep = document.createElement('span');
  sep.className = 'breadcrumb-sep';
  sep.textContent = '›';

  const current = document.createElement('span');
  current.className = 'breadcrumb-current';
  current.textContent = need.name;

  const switcherBtn = document.createElement('button');
  switcherBtn.className = 'need-switcher-btn';
  switcherBtn.textContent = '▾';
  switcherBtn.setAttribute('aria-label', 'Switch need');
  switcherBtn.addEventListener('click', e => {
    e.stopPropagation();
    showNeedSwitcher(switcherBtn);
  });

  nav.append(backBtn, sep, current, switcherBtn);
  header.appendChild(nav);

  const headerText = document.createElement('div');
  const h1 = document.createElement('h1');
  h1.className = 'board-need-name';
  h1.textContent = need.name;
  headerText.appendChild(h1);
  if (need.description) {
    const desc = document.createElement('p');
    desc.className = 'board-need-desc';
    desc.textContent = need.description;
    headerText.appendChild(desc);
  }
  header.appendChild(headerText);
  stageEl.appendChild(header);

  // Board
  const board = document.createElement('div');
  board.className = 'board';

  const directTasks = need.tasks || [];
  if (directTasks.length) {
    board.appendChild(buildSubneedCol(
      { name: 'Direct Tasks', description: '', tasks: directTasks },
      need.id
    ));
  }
  for (const sub of (need.subneeds || [])) {
    board.appendChild(buildSubneedCol(sub, need.id));
  }
  stageEl.appendChild(board);

  // ── FLIP animation ────────────────────────────────────────────────────────
  if (fromRect) {
    const toRect = header.getBoundingClientRect();
    const dx = fromRect.left - toRect.left;
    const dy = fromRect.top  - toRect.top;
    const sx = fromRect.width  / Math.max(toRect.width,  1);
    const sy = fromRect.height / Math.max(toRect.height, 1);

    header.style.transformOrigin = 'top left';
    header.style.transform = `translate(${dx}px,${dy}px) scale(${sx},${sy})`;
    header.style.opacity = '0.5';
    void header.offsetWidth;
    header.style.transition = 'transform 0.32s cubic-bezier(0.25,0.46,0.45,0.94), opacity 0.2s ease';
    header.style.transform = '';
    header.style.opacity   = '';
    header.addEventListener('transitionend', () => {
      header.style.transition = header.style.transformOrigin = '';
    }, { once: true });

    const cols = board.querySelectorAll('.subneed-col');
    cols.forEach((col, i) => {
      col.style.opacity   = '0';
      col.style.transform = 'translateY(10px)';
      void col.offsetWidth;
      const delay = `${0.08 + i * 0.04}s`;
      col.style.transition = `opacity 0.22s ease ${delay}, transform 0.22s ease ${delay}`;
      col.style.opacity   = '';
      col.style.transform = '';
      col.addEventListener('transitionend', () => {
        col.style.transition = col.style.opacity = col.style.transform = '';
      }, { once: true });
    });
  }
}

function navigateBack() {
  if (prefersReducedMotion()) { renderOverview(); return; }

  stageEl.style.opacity   = '0';
  stageEl.style.transition = 'opacity 0.18s ease';
  stageEl.addEventListener('transitionend', () => {
    stageEl.style.transition = stageEl.style.opacity = '';
    renderOverview();
    stageEl.style.opacity   = '0';
    void stageEl.offsetWidth;
    stageEl.style.transition = 'opacity 0.18s ease';
    stageEl.style.opacity   = '';
    stageEl.addEventListener('transitionend', () => {
      stageEl.style.transition = '';
    }, { once: true });
  }, { once: true });
}

function buildSubneedCol(subneed, needId) {
  const col = document.createElement('div');
  col.className = 'subneed-col';

  const hdr = document.createElement('div');
  hdr.className = 'col-header';
  setAccent(hdr, needId);

  const colName = document.createElement('div');
  colName.className = 'col-name';
  colName.textContent = subneed.name;
  hdr.appendChild(colName);

  if (subneed.description) {
    const colDesc = document.createElement('div');
    colDesc.className = 'col-desc';
    colDesc.textContent = subneed.description;
    hdr.appendChild(colDesc);
  }

  const colCount = document.createElement('div');
  colCount.className = 'col-count';
  const n = (subneed.tasks || []).length;
  colCount.textContent = `${n} task${n !== 1 ? 's' : ''}`;
  hdr.appendChild(colCount);
  col.appendChild(hdr);

  const cards = document.createElement('div');
  cards.className = 'col-cards';
  for (const task of (subneed.tasks || [])) {
    cards.appendChild(buildTaskCard(task));
  }
  col.appendChild(cards);
  return col;
}

function buildTaskCard(task) {
  const card = document.createElement('div');
  card.className = 'task-card';
  card.dataset.id = task.id;
  if (task.id === state.selectedId) card.classList.add('selected');

  const name = document.createElement('div');
  name.className = 'task-name';
  name.textContent = task.name;
  card.appendChild(name);

  if (sharedIds.has(task.id)) {
    const others = getOtherNeedsForTask(task.id);
    if (others.length) {
      const dots = document.createElement('div');
      dots.className = 'reuse-dots';
      const names = others.map(n => n.name).join(', ');
      dots.title = `Also in: ${names}`;
      for (const need of others) {
        const dot = document.createElement('span');
        dot.className = 'reuse-dot';
        const color = state.needColors.get(need.id);
        if (color) dot.style.background = color.hex;
        dot.title = need.name;
        dots.appendChild(dot);
      }
      card.appendChild(dots);
    }
  }

  card.addEventListener('click', e => { e.stopPropagation(); selectItem(task.id); });
  return card;
}

// ── Selection & Drawer ────────────────────────────────────────────────────────

function selectItem(id) {
  state.selectedId = id;
  for (const card of document.querySelectorAll('.task-card')) {
    card.classList.toggle('selected', card.dataset.id === id);
  }
  openDrawer(id);
}

function openDrawer(id) {
  drawerEl.classList.add('open');
  renderDrawer(id);
}

function closeDrawer() {
  drawerEl.classList.remove('open');
  state.selectedId = null;
  for (const card of document.querySelectorAll('.task-card')) {
    card.classList.remove('selected');
  }
}

function renderDrawer(id) {
  const node = state.graph?.nodes.find(n => n.id === id);
  drawerEl.innerHTML = '';
  if (!node) return;

  const type = getType(node);

  const inner = document.createElement('div');
  inner.className = 'drawer-inner';

  // Header
  const hdr = document.createElement('div');
  hdr.className = 'drawer-header';

  const top = document.createElement('div');
  top.className = 'drawer-header-top';

  const pill = document.createElement('span');
  pill.className = 'pill';
  pill.textContent = type;

  const closeBtn = document.createElement('button');
  closeBtn.className = 'drawer-close';
  closeBtn.setAttribute('aria-label', 'Close');
  closeBtn.textContent = '✕';
  closeBtn.addEventListener('click', closeDrawer);

  top.append(pill, closeBtn);
  hdr.appendChild(top);

  const title = document.createElement('h2');
  title.className = 'drawer-title';
  title.textContent = node.name;
  hdr.appendChild(title);

  if (node.description) {
    const desc = document.createElement('p');
    desc.className = 'drawer-desc';
    desc.textContent = node.description;
    hdr.appendChild(desc);
  }

  inner.appendChild(hdr);

  // Body
  const body = document.createElement('div');
  body.className = 'drawer-body';

  if (type === 'Task') {
    const homes = getTaskHomes(id);
    const sec = document.createElement('div');
    sec.className = 'drawer-section';

    const label = document.createElement('div');
    label.className = 'drawer-section-label';
    label.textContent = 'Where it lives';
    sec.appendChild(label);

    const ul = document.createElement('ul');
    ul.className = 'drawer-homes';

    for (const home of homes) {
      const color = state.needColors.get(home.needId);
      const li = document.createElement('li');
      li.className = 'drawer-home-item';

      const dot = document.createElement('span');
      dot.className = 'drawer-home-dot';
      if (color) dot.style.background = color.hex;

      const needName = document.createElement('span');
      needName.className = 'drawer-home-need';
      needName.textContent = home.needName;

      const jump = document.createElement('button');
      jump.className = 'drawer-jump';
      jump.textContent = 'Go →';
      const { needId } = home;
      jump.addEventListener('click', () => jumpToNeed(needId, id));

      li.append(dot, needName, jump);

      if (home.subneedName) {
        const sub = document.createElement('span');
        sub.className = 'drawer-home-subneed';
        sub.textContent = `› ${home.subneedName}`;
        li.appendChild(sub);
      }

      ul.appendChild(li);
    }

    sec.appendChild(ul);
    body.appendChild(sec);
  } else {
    // Subneed/Need: show parent info
    const parentRels = (state.graph?.relationships || []).filter(r => r.target === id);
    if (parentRels.length) {
      const sec = document.createElement('div');
      sec.className = 'drawer-section';

      const label = document.createElement('div');
      label.className = 'drawer-section-label';
      label.textContent = 'Parent';
      sec.appendChild(label);

      const ul = document.createElement('ul');
      for (const r of parentRels) {
        const parent = state.graph.nodes.find(n => n.id === r.source);
        if (!parent) continue;
        const li = document.createElement('li');
        li.className = 'detail-item';
        const nm  = document.createElement('span');
        nm.textContent = parent.name;
        const rel = document.createElement('span');
        rel.className = 'detail-item-rel';
        rel.textContent = r.type;
        li.append(nm, rel);
        ul.appendChild(li);
      }
      sec.appendChild(ul);
      body.appendChild(sec);
    }
  }

  inner.appendChild(body);
  drawerEl.appendChild(inner);
}

function jumpToNeed(needId, taskId) {
  const need = state.graph.hierarchy.find(n => n.id === needId);
  if (!need) return;
  closeDrawer();
  navigateToNeed(need, null);
  requestAnimationFrame(() => {
    selectItem(taskId);
    const card = document.querySelector(`.task-card[data-id="${CSS.escape(taskId)}"]`);
    if (card) {
      card.scrollIntoView({ behavior: 'smooth', block: 'center' });
      card.classList.add('pulse');
      setTimeout(() => card.classList.remove('pulse'), 600);
    }
  });
}

// ── Need switcher ─────────────────────────────────────────────────────────────

function showNeedSwitcher(anchorEl) {
  closePopover();
  const pop = document.createElement('div');
  pop.className = 'need-switcher-popover';

  for (const need of state.graph.hierarchy) {
    const btn = document.createElement('button');
    btn.className = 'switcher-item';
    setAccent(btn, need.id);
    if (need.id === state.activeNeed?.id) btn.classList.add('active');

    const dot = document.createElement('span');
    dot.className = 'switcher-dot';
    const label = document.createElement('span');
    label.textContent = need.name;
    btn.append(dot, label);
    btn.addEventListener('click', () => { closePopover(); navigateToNeed(need, null); });
    pop.appendChild(btn);
  }

  document.body.appendChild(pop);

  const r  = anchorEl.getBoundingClientRect();
  pop.style.top  = `${r.bottom + 6}px`;
  pop.style.left = `${r.left}px`;
  const pr = pop.getBoundingClientRect();
  if (pr.right > window.innerWidth - 8)
    pop.style.left = `${Math.max(8, window.innerWidth - 8 - pr.width)}px`;

  openPopover = pop;
}

function closePopover() {
  if (openPopover) { openPopover.remove(); openPopover = null; }
}

// ── Search (command palette) ──────────────────────────────────────────────────

function openSearch() {
  searchOverlay.classList.remove('hidden');
  searchInput.value = '';
  searchResults.innerHTML = '';
  searchInput.focus();
}

function closeSearch() {
  searchOverlay.classList.add('hidden');
}

function runSearch(query) {
  const q = query.trim().toLowerCase();
  searchResults.innerHTML = '';
  if (!q || !state.graph) return;

  const needs    = [];
  const subneeds = [];
  const tasks    = [];
  const seenTask = new Set();

  for (const need of state.graph.hierarchy) {
    if (need.name.toLowerCase().includes(q))
      needs.push({ node: need, needId: need.id, needName: null });

    for (const sub of (need.subneeds || [])) {
      if (sub.name.toLowerCase().includes(q))
        subneeds.push({ node: sub, needId: need.id, needName: need.name });

      for (const task of (sub.tasks || [])) {
        if (task.name.toLowerCase().includes(q) && !seenTask.has(task.id)) {
          seenTask.add(task.id);
          tasks.push({ node: task, needId: need.id, needName: need.name });
        }
      }
    }

    for (const task of (need.tasks || [])) {
      if (task.name.toLowerCase().includes(q) && !seenTask.has(task.id)) {
        seenTask.add(task.id);
        tasks.push({ node: task, needId: need.id, needName: need.name });
      }
    }
  }

  const groups = [
    { label: 'Needs',    items: needs    },
    { label: 'Subneeds', items: subneeds },
    { label: 'Tasks',    items: tasks    },
  ];

  let any = false;
  for (const { label, items } of groups) {
    if (!items.length) continue;
    any = true;
    const groupEl = document.createElement('div');
    groupEl.className = 'search-group';

    const groupLabel = document.createElement('div');
    groupLabel.className = 'search-group-label';
    groupLabel.textContent = label;
    groupEl.appendChild(groupLabel);

    for (const item of items) {
      const row = document.createElement('button');
      row.className = 'search-result-item';

      const dot = document.createElement('span');
      dot.className = 'search-result-dot';
      const color = state.needColors.get(item.needId);
      if (color) dot.style.background = color.hex;

      const name = document.createElement('span');
      name.className = 'search-result-name';
      name.textContent = item.node.name;

      row.append(dot, name);

      if (item.needName) {
        const meta = document.createElement('span');
        meta.className = 'search-result-meta';
        meta.textContent = item.needName;
        row.appendChild(meta);
      }

      row.addEventListener('click', () => {
        closeSearch();
        const need = state.graph.hierarchy.find(n => n.id === item.needId);
        if (!need) return;
        if (label === 'Needs') {
          navigateToNeed(need, null);
        } else {
          navigateToNeed(need, null);
          requestAnimationFrame(() => {
            if (label === 'Tasks') selectItem(item.node.id);
            const card = document.querySelector(`[data-id="${CSS.escape(item.node.id)}"]`);
            if (card) {
              card.scrollIntoView({ behavior: 'smooth', block: 'center' });
              card.classList.add('pulse');
              setTimeout(() => card.classList.remove('pulse'), 600);
            }
          });
        }
      });

      groupEl.appendChild(row);
    }
    searchResults.appendChild(groupEl);
  }

  if (!any) {
    searchResults.innerHTML = '<div class="search-empty">No results</div>';
  }
}

// ── Events ────────────────────────────────────────────────────────────────────

document.querySelector('#search-trigger').addEventListener('click', openSearch);
document.querySelector('#search-backdrop').addEventListener('click', closeSearch);
searchInput.addEventListener('input', e => runSearch(e.target.value));

document.addEventListener('keydown', e => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
    e.preventDefault();
    openSearch();
    return;
  }
  if (e.key === 'Escape') {
    if (!searchOverlay.classList.contains('hidden')) { closeSearch(); return; }
    if (openPopover) { closePopover(); return; }
    closeDrawer();
  }
});

document.querySelector('#overflow-btn').addEventListener('click', e => {
  e.stopPropagation();
  overflowMenu.classList.toggle('hidden');
});

document.addEventListener('click', e => {
  if (openPopover && !openPopover.contains(e.target) && !e.target.closest('.need-switcher-btn'))
    closePopover();
  if (!overflowMenu.classList.contains('hidden') &&
      !overflowMenu.contains(e.target) &&
      e.target !== document.querySelector('#overflow-btn'))
    overflowMenu.classList.add('hidden');
});

stageEl.addEventListener('click', e => {
  if (!e.target.closest('.task-card') && !e.target.closest('.need-card'))
    closeDrawer();
});

document.querySelector('#load-json').addEventListener('click',  () => { overflowMenu.classList.add('hidden'); loadJson(); });
document.querySelector('#export-json').addEventListener('click', () => { overflowMenu.classList.add('hidden'); exportJson(); });
document.querySelector('#wipe-graph').addEventListener('click',  () => { overflowMenu.classList.add('hidden'); wipeGraph(); });

loadGraph();
