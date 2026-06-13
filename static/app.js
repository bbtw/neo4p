const state = {
  graph: null,
  selectedId: null,
  query: "",
};

const typeOrder = { Need: 0, Subneed: 1, Task: 2 };
const svg = document.querySelector("#graph");
const hierarchyEl = document.querySelector("#hierarchy");
const searchEl = document.querySelector("#search");
const actionButtons = [...document.querySelectorAll(".graph-actions button")];
const loadJsonButton = document.querySelector("#load-json");
const exportJsonButton = document.querySelector("#export-json");
const wipeGraphButton = document.querySelector("#wipe-graph");

async function loadGraph() {
  try {
    const response = await fetch("/api/graph");
    if (!response.ok) throw new Error(await response.text());
    state.graph = await response.json();
    render();
  } catch (error) {
    hierarchyEl.innerHTML = `<p class="empty">Could not load Neo4j graph. Import the seed data and check Neo4j credentials.</p>`;
    document.querySelector("#detail-description").textContent = error.message;
  }
}

async function postGraphAction(path) {
  const response = await fetch(path, { method: "POST" });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || response.statusText);
  return body;
}

async function loadJson() {
  if (!confirm("Replace the Neo4j planning graph with data/financial-planning-graph.json?")) return;
  setBusy(true);
  try {
    const result = await postGraphAction("/api/graph/import");
    state.selectedId = null;
    await loadGraph();
    setDetailMessage(`Loaded ${result.nodes} nodes and ${result.relationships} relationships.`);
  } catch (error) {
    setDetailMessage(error.message);
  } finally {
    setBusy(false);
  }
}

async function exportJson() {
  setBusy(true);
  try {
    const response = await fetch("/api/graph/export");
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || response.statusText);
    downloadJson(body);
    setDetailMessage(`Exported ${body.nodes.length} nodes and ${body.relationships.length} relationships.`);
  } catch (error) {
    setDetailMessage(error.message);
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
    await loadGraph();
    setDetailMessage("Planning graph wiped.");
  } catch (error) {
    setDetailMessage(error.message);
  } finally {
    setBusy(false);
  }
}

function downloadJson(value) {
  const blob = new Blob([`${JSON.stringify(value, null, 2)}\n`], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "financial-planning-graph.json";
  link.click();
  URL.revokeObjectURL(url);
}

function setBusy(isBusy) {
  for (const button of actionButtons) {
    button.disabled = isBusy;
  }
}

function setDetailMessage(message) {
  document.querySelector("#detail-title").textContent = "Graph";
  document.querySelector("#detail-type").textContent = "Status";
  document.querySelector("#detail-description").textContent = message;
  renderList("#parents", []);
  renderList("#children", []);
}

function render() {
  updateMetrics();
  renderHierarchy();
  renderGraph();
}

function updateMetrics() {
  const counts = { Need: 0, Subneed: 0, Task: 0 };
  for (const node of state.graph.nodes) {
    counts[getType(node)] += 1;
  }
  document.querySelector("#need-count").textContent = counts.Need;
  document.querySelector("#subneed-count").textContent = counts.Subneed;
  document.querySelector("#task-count").textContent = counts.Task;
}

function renderHierarchy() {
  hierarchyEl.textContent = "";
  for (const need of state.graph.hierarchy) {
    if (!matchesBranch(need)) continue;
    hierarchyEl.appendChild(nodeButton(need, "need"));

    for (const task of need.tasks || []) {
      if (matchesNode(task)) hierarchyEl.appendChild(nodeButton(task, "task"));
    }

    for (const subneed of need.subneeds || []) {
      if (!matchesBranch(subneed)) continue;
      hierarchyEl.appendChild(nodeButton(subneed, "subneed"));
      for (const task of subneed.tasks || []) {
        if (matchesNode(task)) hierarchyEl.appendChild(nodeButton(task, "task"));
      }
    }
  }
}

function nodeButton(node, className) {
  const button = document.createElement("button");
  button.className = `${className}${node.id === state.selectedId ? " selected" : ""}`;
  button.type = "button";
  button.textContent = node.name;
  button.addEventListener("click", () => selectNode(node.id));
  return button;
}

function matchesBranch(node) {
  if (matchesNode(node)) return true;
  for (const subneed of node.subneeds || []) {
    if (matchesBranch(subneed)) return true;
  }
  for (const task of node.tasks || []) {
    if (matchesNode(task)) return true;
  }
  return false;
}

function matchesNode(node) {
  if (!state.query) return true;
  return node.name.toLowerCase().includes(state.query);
}

function renderGraph() {
  const width = svg.clientWidth || 900;
  const height = svg.clientHeight || 600;
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.textContent = "";

  const nodes = state.graph.nodes
    .filter(matchesNode)
    .sort((a, b) => typeOrder[getType(a)] - typeOrder[getType(b)] || a.name.localeCompare(b.name));
  const visible = new Set(nodes.map((node) => node.id));
  const relationships = state.graph.relationships.filter(
    (relationship) => visible.has(relationship.source) && visible.has(relationship.target),
  );
  const positions = layout(nodes, relationships, width, height);

  for (const relationship of relationships) {
    const from = positions.get(relationship.source);
    const to = positions.get(relationship.target);
    if (!from || !to) continue;
    const line = svgEl("line", {
      class: "edge",
      x1: from.x,
      y1: from.y,
      x2: to.x,
      y2: to.y,
    });
    svg.appendChild(line);
  }

  for (const node of nodes) {
    const position = positions.get(node.id);
    const type = getType(node);
    const group = svgEl("g", {
      class: `node ${type}${node.id === state.selectedId ? " active" : ""}`,
      transform: `translate(${position.x}, ${position.y})`,
    });
    group.appendChild(svgEl("circle", { r: type === "Need" ? 13 : type === "Subneed" ? 10 : 7 }));
    group.appendChild(svgEl("text", { x: 15, y: 4 }, truncate(node.name, 34)));
    group.addEventListener("click", () => selectNode(node.id));
    svg.appendChild(group);
  }
}

function layout(nodes, relationships, width, height) {
  const byParent = new Map();
  const incoming = new Set();
  for (const relationship of relationships) {
    incoming.add(relationship.target);
    if (!byParent.has(relationship.source)) byParent.set(relationship.source, []);
    byParent.get(relationship.source).push(relationship.target);
  }

  const roots = nodes.filter((node) => getType(node) === "Need" || !incoming.has(node.id));
  const positions = new Map();
  const xByType = {
    Need: Math.max(90, width * 0.12),
    Subneed: Math.max(260, width * 0.42),
    Task: Math.max(470, width * 0.72),
  };
  const rowHeight = Math.max(34, Math.min(54, (height - 70) / Math.max(nodes.length, 1)));
  let row = 1;

  function place(nodeId) {
    const node = nodes.find((candidate) => candidate.id === nodeId);
    if (!node || positions.has(nodeId)) return;
    const type = getType(node);
    positions.set(nodeId, { x: xByType[type], y: 30 + row * rowHeight });
    row += 1;
    for (const childId of byParent.get(nodeId) || []) {
      place(childId);
    }
  }

  for (const root of roots) place(root.id);
  for (const node of nodes) place(node.id);
  return positions;
}

async function selectNode(id) {
  state.selectedId = id;
  render();
  const response = await fetch(`/api/nodes/${encodeURIComponent(id)}`);
  if (!response.ok) return;
  const node = await response.json();
  document.querySelector("#detail-title").textContent = node.name;
  document.querySelector("#detail-type").textContent = getType(node);
  document.querySelector("#detail-description").textContent = node.description || "No description yet.";
  renderList("#parents", node.parents);
  renderList("#children", node.children);
}

function renderList(selector, items) {
  const list = document.querySelector(selector);
  list.textContent = "";
  if (!items.length) {
    const item = document.createElement("li");
    item.className = "empty";
    item.textContent = "None";
    list.appendChild(item);
    return;
  }
  for (const value of items.sort((a, b) => a.name.localeCompare(b.name))) {
    const item = document.createElement("li");
    item.textContent = `${value.name} (${value.relationship})`;
    list.appendChild(item);
  }
}

function getType(node) {
  if (node.type) return node.type;
  if (node.labels.includes("Need")) return "Need";
  if (node.labels.includes("Subneed")) return "Subneed";
  return "Task";
}

function svgEl(name, attributes, text) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", name);
  for (const [key, value] of Object.entries(attributes)) {
    element.setAttribute(key, value);
  }
  if (text) element.textContent = text;
  return element;
}

function truncate(value, max) {
  return value.length > max ? `${value.slice(0, max - 1)}...` : value;
}

searchEl.addEventListener("input", (event) => {
  state.query = event.target.value.trim().toLowerCase();
  render();
});

loadJsonButton.addEventListener("click", loadJson);
exportJsonButton.addEventListener("click", exportJson);
wipeGraphButton.addEventListener("click", wipeGraph);

window.addEventListener("resize", () => {
  if (state.graph) renderGraph();
});

loadGraph();
