// ── Layout constants ──────────────────────────────────────────────────────────

const CARD_W  = 220;
const CARD_H  = 50;
const ROW_GAP = 8;
const COL_GAP = 56;   // horizontal gap between right edge of parent and left edge of child
const PAD_X   = 24;
const PAD_Y   = 20;
const STUB    = 20;   // horizontal stub from parent right to vertical bus

const COL_X = [PAD_X, PAD_X + CARD_W + COL_GAP, PAD_X + 2 * (CARD_W + COL_GAP)];
const CANVAS_W = COL_X[2] + CARD_W + PAD_X;

// ── State ─────────────────────────────────────────────────────────────────────

const state = {
  graph: null,
  selectedId: null,
  hoverId: null,
  query: "",
  expanded: new Set(),
};

let sharedIds = new Set();
let lastLayout = null;
let openPopover = null;

// ── DOM refs ──────────────────────────────────────────────────────────────────

const treeCanvas    = document.querySelector("#tree-canvas");
const connectorSvg  = document.querySelector("#connector-layer");
const searchEl      = document.querySelector("#search");
const actionButtons = [...document.querySelectorAll(".graph-actions button")];

// ── API ───────────────────────────────────────────────────────────────────────

async function loadGraph() {
  try {
    const res = await fetch("/api/graph");
    if (!res.ok) throw new Error(await res.text());
    state.graph = await res.json();
    sharedIds = buildSharedIds(state.graph.hierarchy);
    for (const need of state.graph.hierarchy) state.expanded.add(need.id);
    render();
  } catch (err) {
    showCanvasMessage("Could not load graph. Import seed data and check Neo4j credentials.");
  }
}

async function postGraphAction(path) {
  const res = await fetch(path, { method: "POST" });
  const body = await res.json();
  if (!res.ok) throw new Error(body.error || res.statusText);
  return body;
}

async function loadJson() {
  if (!confirm("Replace the Neo4j planning graph with data/financial-planning-graph.json?")) return;
  setBusy(true);
  try {
    const result = await postGraphAction("/api/graph/import");
    state.selectedId = null;
    state.expanded = new Set();
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
    const res = await fetch("/api/graph/export");
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
  if (!confirm("Delete all FinancialPlanningGraph nodes and relationships from Neo4j?")) return;
  setBusy(true);
  try {
    await postGraphAction("/api/graph/wipe");
    state.selectedId = null;
    state.expanded = new Set();
    await loadGraph();
    showToast("Planning graph wiped.");
  } catch (err) {
    showToast(err.message);
  } finally {
    setBusy(false);
  }
}

function fetchDetail(id) {
  if (!state.graph) return;
  const node = state.graph.nodes.find(n => n.id === id);
  if (!node) return;

  const byId = new Map(state.graph.nodes.map(n => [n.id, n]));
  const parents = state.graph.relationships
    .filter(r => r.target === id)
    .map(r => ({ id: r.source, name: byId.get(r.source)?.name ?? r.source, relationship: r.type }));
  const children = state.graph.relationships
    .filter(r => r.source === id)
    .map(r => ({ id: r.target, name: byId.get(r.target)?.name ?? r.target, relationship: r.type }));

  document.querySelector("#detail-title").textContent = node.name;
  document.querySelector("#detail-type").textContent  = getType(node);
  document.querySelector("#detail-description").textContent = node.description || "No description.";
  renderDetailList("#parents",  parents);
  renderDetailList("#children", children);
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function getType(node) {
  if (node.type) return node.type;
  const labels = node.labels || [];
  if (labels.includes("Need")) return "Need";
  if (labels.includes("Subneed")) return "Subneed";
  return "Task";
}

function buildSharedIds(hierarchy) {
  const seen = new Set();
  const shared = new Set();
  function walk(nodes) {
    for (const n of nodes) {
      if (seen.has(n.id)) shared.add(n.id);
      else seen.add(n.id);
      walk(n.subneeds || []);
      walk(n.tasks || []);
    }
  }
  walk(hierarchy);
  return shared;
}

function countDescendants(item) {
  let n = 0;
  for (const s of (item.subneeds || [])) n += 1 + countDescendants(s);
  for (const t of (item.tasks || [])) n += 1;
  return n;
}

function matchesNode(node) {
  if (!state.query) return true;
  return node.name.toLowerCase().includes(state.query);
}

function matchesBranch(node) {
  if (matchesNode(node)) return true;
  for (const s of (node.subneeds || [])) if (matchesBranch(s)) return true;
  for (const t of (node.tasks || [])) if (matchesNode(t)) return true;
  return false;
}

function setBusy(busy) {
  for (const btn of actionButtons) btn.disabled = busy;
}

function showToast(msg) {
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = msg;
  document.querySelector("#toast-container").appendChild(toast);
  setTimeout(() => toast.remove(), 4000);
}

function showCanvasMessage(msg) {
  connectorSvg.innerHTML = "";
  for (const el of [...treeCanvas.querySelectorAll(".tree-card, .tree-sizer, .canvas-empty")]) el.remove();
  const p = document.createElement("p");
  p.className = "canvas-empty";
  p.textContent = msg;
  treeCanvas.appendChild(p);
}

function downloadJson(value) {
  const blob = new Blob([JSON.stringify(value, null, 2) + "\n"], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "financial-planning-graph.json";
  a.click();
  URL.revokeObjectURL(url);
}

// ── Layout (left-to-right tree) ───────────────────────────────────────────────

function buildLayout(hierarchy) {
  const nodes = [];
  const edges = [];
  let leafY = PAD_Y;

  function processItem(item, depth, parentKey) {
    const instanceKey = parentKey ? `${item.id}::${parentKey}` : item.id;
    const type = item.type || getType(item);
    const isExp = type !== "Task" && state.expanded.has(item.id);

    // Skip non-matching branches when searching
    if (state.query && !matchesBranch(item)) return null;

    const childNodes = [];
    if (isExp) {
      const childItems = [
        ...(item.subneeds || []).map(s => ({ item: s, depth: depth + 1 })),
        ...(item.tasks   || []).map(t => ({ item: t, depth: depth + 1 })),
      ];
      for (const { item: child, depth: d } of childItems) {
        const cn = processItem(child, d, instanceKey);
        if (cn) {
          childNodes.push(cn);
          edges.push({ fromKey: instanceKey, toKey: cn.instanceKey });
        }
      }
    }

    let y;
    if (childNodes.length === 0) {
      y = leafY;
      leafY += CARD_H + ROW_GAP;
    } else {
      y = (childNodes[0].y + childNodes[childNodes.length - 1].y) / 2;
    }

    const node = {
      id: item.id,
      instanceKey,
      name: item.name,
      type,
      depth,
      x: COL_X[Math.min(depth, 2)],
      y,
      isExpanded: isExp,
      isShared: sharedIds.has(item.id),
      childCount: countDescendants(item),
      isMatch: state.query ? matchesNode(item) : false,
    };
    nodes.push(node);
    return node;
  }

  for (const need of hierarchy) {
    processItem(need, 0, null);
  }

  return { nodes, edges, totalHeight: Math.max(leafY + PAD_Y, 200) };
}

// ── Highlight ─────────────────────────────────────────────────────────────────

function computeHighlight(nodes, edges) {
  const { selectedId, hoverId } = state;
  if (!selectedId && !hoverId) return { selected: null, hovered: null };

  const parentOf   = new Map(edges.map(e => [e.toKey, e.fromKey]));
  const childrenOf = new Map();
  for (const e of edges) {
    if (!childrenOf.has(e.fromKey)) childrenOf.set(e.fromKey, []);
    childrenOf.get(e.fromKey).push(e.toKey);
  }

  function ancestorKeys(instanceKey) {
    const result = new Set();
    let k = instanceKey;
    while (parentOf.has(k)) { k = parentOf.get(k); result.add(k); }
    return result;
  }

  let selected = null;
  if (selectedId) {
    selected = new Set();
    for (const n of nodes.filter(n => n.id === selectedId)) {
      selected.add(n.instanceKey);
      for (const k of ancestorKeys(n.instanceKey)) selected.add(k);
      for (const ck of (childrenOf.get(n.instanceKey) || [])) selected.add(ck);
    }
  }

  let hovered = null;
  if (hoverId && hoverId !== selectedId) {
    hovered = new Set();
    for (const n of nodes.filter(n => n.id === hoverId)) {
      hovered.add(n.instanceKey);
      for (const k of ancestorKeys(n.instanceKey)) hovered.add(k);
    }
  }

  return { selected, hovered };
}

// ── Render ────────────────────────────────────────────────────────────────────

function render() {
  if (!state.graph) return;
  updateMetrics();
  renderTree();
}

function updateMetrics() {
  const counts = { Need: 0, Subneed: 0, Task: 0 };
  for (const n of state.graph.nodes) {
    const t = getType(n);
    counts[t] = (counts[t] || 0) + 1;
  }
  document.querySelector("#need-count").textContent    = counts.Need    || 0;
  document.querySelector("#subneed-count").textContent = counts.Subneed || 0;
  document.querySelector("#task-count").textContent    = counts.Task    || 0;
}

function renderTree() {
  for (const el of [...treeCanvas.querySelectorAll(".tree-card, .tree-sizer, .canvas-empty")]) el.remove();

  if (!state.graph || !state.graph.hierarchy.length) {
    connectorSvg.innerHTML = "";
    return;
  }

  const layout = buildLayout(state.graph.hierarchy);
  lastLayout   = layout;
  const { nodes, edges, totalHeight } = layout;

  if (!nodes.length) {
    connectorSvg.innerHTML = "";
    showCanvasMessage("No nodes match your search.");
    return;
  }

  // Force scroll dimensions via an off-canvas 1px sizer
  const sizer = document.createElement("div");
  sizer.className = "tree-sizer";
  sizer.style.cssText = `position:absolute;left:${CANVAS_W}px;top:${totalHeight}px;width:1px;height:1px;pointer-events:none`;
  treeCanvas.appendChild(sizer);

  // Connectors
  connectorSvg.setAttribute("width",   CANVAS_W);
  connectorSvg.setAttribute("height",  totalHeight);
  connectorSvg.setAttribute("viewBox", `0 0 ${CANVAS_W} ${totalHeight}`);
  connectorSvg.innerHTML = buildConnectorPaths(nodes, edges, null);

  // Cards
  for (const node of nodes) {
    const card = buildCard(node);
    treeCanvas.appendChild(card);
  }

  updateHighlight();
}

function buildConnectorPaths(nodes, edges, highlight) {
  const byKey     = new Map(nodes.map(n => [n.instanceKey, n]));
  const byParent  = new Map();
  for (const e of edges) {
    if (!byParent.has(e.fromKey)) byParent.set(e.fromKey, []);
    byParent.get(e.fromKey).push(e.toKey);
  }

  const radius = 6;
  let html = "";
  for (const [fromKey, toKeys] of byParent) {
    const parent   = byKey.get(fromKey);
    if (!parent) continue;
    const children = toKeys.map(k => byKey.get(k)).filter(Boolean);
    if (!children.length) continue;

    const px     = parent.x + CARD_W;
    const py     = parent.y + CARD_H / 2;
    const busX   = children[0].x - STUB;
    const firstY = children[0].y + CARD_H / 2;
    const lastY  = children[children.length - 1].y + CARD_H / 2;

    // Determine if this path is highlighted
    const isHighlighted = highlight && (
      highlight.selected?.has(fromKey) ||
      children.some(c => highlight.selected?.has(c.instanceKey)) ||
      (highlight.hovered && (highlight.hovered.has(fromKey) || children.some(c => highlight.hovered.has(c.instanceKey))))
    );

    const connClass = isHighlighted ? "connector highlighted" : "connector";

    // Stub from parent to bus with rounded corner
    html += `<path class="${connClass}" d="M ${px} ${py} L ${busX - radius} ${py} Q ${busX} ${py} ${busX} ${py < firstY ? firstY - radius : firstY + radius}" />`;

    // Vertical bus spanning all children
    if (children.length > 1) {
      const busStartY = py < firstY ? firstY - radius : firstY + radius;
      const busEndY = py < lastY ? lastY - radius : lastY + radius;
      html += `<path class="${connClass}" d="M ${busX} ${busStartY} L ${busX} ${busEndY}" />`;
    }

    // Branches from bus to each child
    for (const child of children) {
      const cy = child.y + CARD_H / 2;
      const busStartY = children.length === 1 ? (py < cy ? cy - radius : cy + radius) : cy;
      html += `<path class="${connClass}" d="M ${busX} ${busStartY} Q ${busX} ${cy} ${busX + radius} ${cy} L ${child.x - radius} ${cy}" />`;
    }
  }
  return html;
}

function buildCard(node) {
  const card = document.createElement("div");
  card.className = `tree-card ${node.type.toLowerCase()}`;
  card.style.left  = node.x + "px";
  card.style.top   = node.y + "px";
  card.style.width = CARD_W + "px";
  card.dataset.id          = node.id;
  card.dataset.instanceKey = node.instanceKey;
  card.dataset.isMatch     = node.isMatch ? "1" : "0";

  // Left accent stripe
  const stripe = document.createElement("div");
  stripe.className = "card-stripe";
  card.appendChild(stripe);

  // Text content
  const content  = document.createElement("div");
  content.className = "card-content";

  const typeLabel = document.createElement("span");
  typeLabel.className = "card-type-label";
  typeLabel.textContent = node.type;

  const name = document.createElement("span");
  name.className = "card-name";
  name.textContent = node.name;
  name.title       = node.name;

  content.appendChild(typeLabel);
  content.appendChild(name);
  card.appendChild(content);

  // Right side: shared badge, child count, caret
  const right = document.createElement("div");
  right.className = "card-right";

  if (node.isShared) {
    const badge = document.createElement("button");
    badge.type      = "button";
    badge.className = "shared-badge";
    badge.title     = "Used in multiple planning areas — click to see where";
    badge.textContent = "shared";
    badge.addEventListener("click", e => { e.stopPropagation(); toggleSharedPopover(node, badge); });
    right.appendChild(badge);
  }

  if (node.type !== "Task") {
    if (!node.isExpanded && node.childCount > 0) {
      const count = document.createElement("span");
      count.className   = "child-count";
      count.textContent = node.childCount;
      right.appendChild(count);
    }
    const caret = document.createElement("button");
    caret.className         = "card-caret";
    caret.type              = "button";
    caret.setAttribute("aria-label", node.isExpanded ? "Collapse" : "Expand");
    caret.textContent       = node.isExpanded ? "▾" : "▸";
    caret.addEventListener("click", e => { e.stopPropagation(); toggleExpand(node.id); });
    right.appendChild(caret);
  }

  card.appendChild(right);

  card.addEventListener("click", () => {
    state.selectedId = node.id;
    updateHighlight();
    fetchDetail(node.id);
  });
  card.addEventListener("mouseenter", () => { state.hoverId = node.id;  updateHighlight(); });
  card.addEventListener("mouseleave", () => { state.hoverId = null; updateHighlight(); });

  return card;
}

// Updates card classes without rebuilding DOM — used for hover, selection, and search highlight.
function updateHighlight() {
  if (!lastLayout) return;

  if (state.query) {
    for (const card of treeCanvas.querySelectorAll(".tree-card")) {
      const isMatch    = card.dataset.isMatch === "1";
      const isSelected = card.dataset.id === state.selectedId;
      card.classList.toggle("selected",    isSelected);
      card.classList.toggle("highlighted", isMatch && !isSelected);
      card.classList.toggle("dimmed",      !isMatch && !isSelected);
    }
    return;
  }

  const { nodes, edges } = lastLayout;
  const { selected, hovered } = computeHighlight(nodes, edges);
  const isDimming = selected !== null;

  // Rebuild connectors with highlight info
  if (selected || hovered) {
    connectorSvg.innerHTML = buildConnectorPaths(nodes, edges, { selected, hovered });
  } else {
    connectorSvg.innerHTML = buildConnectorPaths(nodes, edges, null);
  }

  for (const card of treeCanvas.querySelectorAll(".tree-card")) {
    const instanceKey = card.dataset.instanceKey;
    const nodeId      = card.dataset.id;
    const isSelected  = nodeId === state.selectedId;
    const inSelected  = selected?.has(instanceKey);
    const inHovered   = hovered?.has(instanceKey);
    const isHighlighted = (inSelected || inHovered) && !isSelected;
    const isDimmed      = isDimming && !inSelected && !isSelected;

    card.classList.toggle("selected",    isSelected);
    card.classList.toggle("highlighted", isHighlighted);
    card.classList.toggle("dimmed",      isDimmed);
  }
}

function renderDetailList(selector, items) {
  const list = document.querySelector(selector);
  list.textContent = "";
  if (!items || !items.length) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "None";
    list.appendChild(li);
    return;
  }
  for (const item of [...items].sort((a, b) => a.name.localeCompare(b.name))) {
    const li  = document.createElement("li");
    li.className = "detail-item";
    const nm  = document.createElement("span");
    nm.textContent = item.name;
    const rel = document.createElement("span");
    rel.className  = "detail-item-rel";
    rel.textContent = item.relationship;
    li.appendChild(nm);
    li.appendChild(rel);
    list.appendChild(li);
  }
}

function toggleExpand(id) {
  // FLIP: capture old positions
  const oldLayout = new Map();
  for (const card of treeCanvas.querySelectorAll(".tree-card")) {
    oldLayout.set(card.dataset.instanceKey, {
      x: parseFloat(card.style.left),
      y: parseFloat(card.style.top),
    });
  }

  // Toggle and rebuild
  if (state.expanded.has(id)) state.expanded.delete(id);
  else state.expanded.add(id);
  renderTree();

  // FLIP: invert (apply transform to old positions) and then play (animate back)
  for (const card of treeCanvas.querySelectorAll(".tree-card")) {
    const oldPos = oldLayout.get(card.dataset.instanceKey);
    if (oldPos) {
      const newX = parseFloat(card.style.left);
      const newY = parseFloat(card.style.top);
      card.style.transform = `translate(${oldPos.x - newX}px, ${oldPos.y - newY}px)`;
    } else {
      card.style.opacity = '0';
    }
  }

  // Force reflow, then animate to final state
  void treeCanvas.offsetHeight;
  for (const card of treeCanvas.querySelectorAll(".tree-card")) {
    card.style.transform = '';
    card.style.opacity = '';
  }
}

// ── Shared-node "other parents" popover ─────────────────────────────────────────

// The immediate parents of this node, by id, excluding the one this instance sits
// under. instanceKey is the reversed id-path joined by "::", so segment [1] is the
// current parent's id (undefined for a root).
function otherParents(node) {
  const byId = new Map(state.graph.nodes.map(n => [n.id, n]));
  const currentParentId = node.instanceKey.split("::")[1];
  const seen = new Set();
  const out  = [];
  for (const r of state.graph.relationships) {
    if (r.target !== node.id) continue;
    const pid = r.source;
    if (pid === currentParentId || seen.has(pid)) continue;
    seen.add(pid);
    const pnode = byId.get(pid);
    out.push({ id: pid, name: pnode?.name ?? pid, type: pnode ? getType(pnode) : "" });
  }
  return out;
}

// First root→target id-path through the hierarchy, or null.
function findIdPath(targetId) {
  let found = null;
  function walk(item, path) {
    if (found) return;
    const next = [...path, item.id];
    if (item.id === targetId) { found = next; return; }
    for (const c of (item.subneeds || [])) walk(c, next);
    for (const t of (item.tasks    || [])) walk(t, next);
  }
  for (const root of state.graph.hierarchy) walk(root, []);
  return found;
}

// Reveal the shared node where it lives under `parentId`: expand that branch,
// select the node, and scroll its instance into view.
function jumpToParent(sharedId, parentId) {
  const path = findIdPath(parentId);
  if (!path) return;
  for (const pid of path) state.expanded.add(pid);
  state.selectedId = sharedId;
  renderTree();
  fetchDetail(sharedId);
  const parentKey = [...path].reverse().join("::");
  const targetKey = `${sharedId}::${parentKey}`;
  const card = treeCanvas.querySelector(`[data-instance-key="${CSS.escape(targetKey)}"]`);
  if (card) {
    card.scrollIntoView({ behavior: "smooth", block: "center", inline: "center" });
    card.classList.add("pulse");
    setTimeout(() => card.classList.remove("pulse"), 600);
  }
}

function closeSharedPopover() {
  if (openPopover) { openPopover.remove(); openPopover = null; }
}

function positionPopover(pop, anchorEl) {
  const r = anchorEl.getBoundingClientRect();
  pop.style.top  = `${r.bottom + 6}px`;
  pop.style.left = `${r.left}px`;
  const pr = pop.getBoundingClientRect();
  if (pr.right > window.innerWidth - 8)
    pop.style.left = `${Math.max(8, window.innerWidth - 8 - pr.width)}px`;
  if (pr.bottom > window.innerHeight - 8)
    pop.style.top = `${Math.max(8, r.top - 6 - pr.height)}px`;
}

function toggleSharedPopover(node, anchorEl) {
  const wasOpenForThis = openPopover && openPopover.dataset.for === node.instanceKey;
  closeSharedPopover();
  if (wasOpenForThis) return;

  const others = otherParents(node);
  const pop = document.createElement("div");
  pop.className   = "shared-popover";
  pop.dataset.for = node.instanceKey;

  const head = document.createElement("div");
  head.className   = "shared-popover-head";
  head.textContent = others.length ? "Also appears under" : "No other parents";
  pop.appendChild(head);

  if (others.length) {
    const ul = document.createElement("ul");
    ul.className = "shared-popover-list";
    for (const p of others) {
      const li = document.createElement("li");
      li.className = "shared-popover-item";
      li.tabIndex  = 0;
      const nm = document.createElement("span");
      nm.className   = "shared-popover-name";
      nm.textContent = p.name;
      const ty = document.createElement("span");
      ty.className   = "shared-popover-type";
      ty.textContent = p.type;
      li.append(nm, ty);
      const go = () => { closeSharedPopover(); jumpToParent(node.id, p.id); };
      li.addEventListener("click", e => { e.stopPropagation(); go(); });
      li.addEventListener("keydown", e => { if (e.key === "Enter") { e.stopPropagation(); go(); } });
      ul.appendChild(li);
    }
    pop.appendChild(ul);
  }

  document.body.appendChild(pop);
  positionPopover(pop, anchorEl);
  openPopover = pop;
}

// ── Events ────────────────────────────────────────────────────────────────────

searchEl.addEventListener("input", e => {
  state.query = e.target.value.trim().toLowerCase();
  render();
});

// Clear the selection by clicking empty canvas or pressing Escape.
function clearSelection() {
  if (!state.selectedId) return;
  state.selectedId = null;
  updateHighlight();
}

treeCanvas.addEventListener("click", e => {
  if (!e.target.closest(".tree-card")) clearSelection();
});

document.addEventListener("keydown", e => {
  if (e.key !== "Escape") return;
  if (openPopover) closeSharedPopover();
  else clearSelection();
});

document.addEventListener("click", e => {
  if (openPopover && !openPopover.contains(e.target) && !e.target.closest(".shared-badge"))
    closeSharedPopover();
});

document.querySelector("#load-json").addEventListener("click",  loadJson);
document.querySelector("#export-json").addEventListener("click", exportJson);
document.querySelector("#wipe-graph").addEventListener("click",  wipeGraph);

loadGraph();
