"""
The declared shape of one knowledge graph.

Every graph this pipeline governs is accompanied by a `shape.yaml` stating,
in plain terms, how to read it: which node labels are client-facing steps,
which are branch points, which relationship types fork, and which edge
attributes hold a branch condition. Nothing here is guessed. If the graph
contradicts the declaration, `check_shape()` fails loudly and validation
stops — a shape file that has drifted from its graph is itself a finding.

This replaces the previous `schema.infer_schema()`, which pattern-matched
those facts out of graph topology on every run. Inference is still available
as a starting point for a graph that has no shape file yet, but it now lives
in `propose_shape.py` and writes a draft for a human to review. It never
runs during validation.

Why declared, not inferred: every check downstream — what counts as a step,
which nodes get collapsed away, which steps must carry `rationale` — hangs
off these five facts. Inferring them means a wrong guess quietly changes
what "passed" means. Declaring them means the reviewer can read the shape
file in fifteen seconds and know exactly what was checked.

A shape.yaml, in full:

    # Which node labels mean what. Read from the node's `labels` attribute,
    # which every graphml export carries (APOC included).
    step_labels:   [Task]
    branch_labels: [CriteriaNode]

    # Relationship types that fork into a branch node.
    branch_rels:   [BRANCHES_TO]

    # Where the condition lives on a branch edge. Both or neither.
    condition_key_attr:   condition_key
    condition_value_attr: condition_value

    # Attributes every step node must carry. Branch nodes are exempt.
    required_step_attrs: [rationale, source_doc]

    # Attributes every branch edge must carry.
    required_branch_attrs: [condition_key, condition_value]
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

# Node/edge attributes that describe the export rather than the domain.
BOOKKEEPING_NODE_ATTRS = frozenset({"labels", "id"})
BOOKKEEPING_EDGE_ATTRS = frozenset({"rel", "id"})

REQUIRED_KEYS = ("step_labels", "branch_labels", "branch_rels")
OPTIONAL_KEYS = (
    "condition_key_attr",
    "condition_value_attr",
    "required_step_attrs",
    "required_branch_attrs",
)

# propose_shape.py writes this wherever the graph gave it ambiguous evidence,
# rather than picking one reading and hoping. A draft still carrying it is
# not a shape file — it is an unanswered question — so loading one is a hard
# error naming exactly which fields a human still has to decide.
UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class GraphShape:
    """What the graph's author says the graph is. Not derived from the graph."""

    step_labels: frozenset
    branch_labels: frozenset
    branch_rels: frozenset
    condition_key_attr: str | None = None
    condition_value_attr: str | None = None
    required_step_attrs: tuple = ()
    required_branch_attrs: tuple = ()
    source: str = "<literal>"

    # -- reading the graph through this shape ------------------------------

    @staticmethod
    def labels_of(data: dict) -> set[str]:
        """A node's labels. APOC writes `labels` as a colon-delimited string
        (":Task", "Task:Archived"); a hand-authored fixture writes a bare
        name. Both parse to the same set."""
        raw = data.get("labels") or data.get("label") or ""
        return {part for part in str(raw).split(":") if part}

    def is_branch_node(self, data: dict) -> bool:
        return bool(self.labels_of(data) & self.branch_labels)

    def is_step_node(self, data: dict) -> bool:
        return bool(self.labels_of(data) & self.step_labels)

    def is_branch_edge(self, data: dict) -> bool:
        return data.get("rel") in self.branch_rels

    def has_condition(self) -> bool:
        return bool(self.condition_key_attr and self.condition_value_attr)

    def describe(self) -> str:
        """One block a reviewer can read to know what was checked. Printed on
        every validation run — the shape is the premise of every result
        below it, so it should never be something you have to go look up."""
        lines = [
            f"shape: {self.source}",
            f"  steps         = nodes labelled {sorted(self.step_labels)}",
            f"  branch points = nodes labelled {sorted(self.branch_labels)}",
            f"  branch rels   = {sorted(self.branch_rels)}",
        ]
        if self.has_condition():
            lines.append(
                f"  condition     = edge[{self.condition_key_attr!r}] names a "
                f"profile field, edge[{self.condition_value_attr!r}] its value"
            )
        else:
            lines.append("  condition     = none declared (scenario walks disabled)")
        lines.append(
            f"  steps must carry  {list(self.required_step_attrs) or '(nothing)'}"
        )
        lines.append(
            f"  branch edges must carry {list(self.required_branch_attrs) or '(nothing)'}"
        )
        return "\n".join(lines)


def load_shape(path: str | Path) -> GraphShape:
    """Read a shape.yaml. Raises ValueError on anything malformed — a shape
    file is a contract, so a typo in it is an error, never a default."""
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        # A malformed shape file is one failure mode among several; callers
        # report it the same way rather than dumping a parser traceback.
        raise ValueError(f"{path}: is not valid YAML: {exc}") from exc
    # ValueError, not TypeError, throughout this function: every caller
    # catches a single exception type and reports "cannot validate: <reason>"
    # — a malformed shape file is one failure mode, however it is malformed.
    if not isinstance(raw, dict):
        raise ValueError(  # noqa: TRY004
            f"{path}: expected a YAML mapping, got {type(raw).__name__}"
        )

    unknown = set(raw) - set(REQUIRED_KEYS) - set(OPTIONAL_KEYS)
    if unknown:
        raise ValueError(
            f"{path}: unknown key(s) {sorted(unknown)}; "
            f"expected any of {sorted(REQUIRED_KEYS + OPTIONAL_KEYS)}"
        )
    missing = [k for k in REQUIRED_KEYS if k not in raw]
    if missing:
        raise ValueError(f"{path}: missing required key(s) {missing}")

    unresolved = sorted(
        key
        for key, value in raw.items()
        if value == UNRESOLVED
        or (isinstance(value, list) and UNRESOLVED in value)
    )
    if unresolved:
        raise ValueError(
            f"{path}: still marked {UNRESOLVED} — {unresolved}. propose_shape.py "
            "could not determine these from the graph and will not guess; the "
            "comment above each one in the file says what it found and what it "
            "needs. Decide each, then re-run."
        )

    for key in REQUIRED_KEYS + ("required_step_attrs", "required_branch_attrs"):
        if key in raw and not isinstance(raw[key], list):
            raise ValueError(
                f"{path}: {key} must be a list, got {type(raw[key]).__name__}"
            )

    key_attr = raw.get("condition_key_attr")
    value_attr = raw.get("condition_value_attr")
    if bool(key_attr) != bool(value_attr):
        raise ValueError(
            f"{path}: condition_key_attr and condition_value_attr must be "
            "declared together or not at all — one without the other silently "
            "makes every conditional edge unconditional"
        )

    overlap = set(raw["step_labels"]) & set(raw["branch_labels"])
    if overlap:
        raise ValueError(
            f"{path}: label(s) {sorted(overlap)} listed as both step and branch"
        )
    if not raw["step_labels"]:
        raise ValueError(f"{path}: step_labels is empty — nothing would be validated")

    return GraphShape(
        step_labels=frozenset(raw["step_labels"]),
        branch_labels=frozenset(raw["branch_labels"]),
        branch_rels=frozenset(raw["branch_rels"]),
        condition_key_attr=key_attr,
        condition_value_attr=value_attr,
        required_step_attrs=tuple(raw.get("required_step_attrs", [])),
        required_branch_attrs=tuple(raw.get("required_branch_attrs", [])),
        source=str(path),
    )


def check_shape(graph, shape: GraphShape) -> list[str]:
    """Does this graph actually look like what the shape file claims?

    Run before any other layer. Every later check reads the graph *through*
    the shape, so a shape that doesn't fit produces confident, meaningless
    results — the exact failure mode inference had. These checks are cheap
    and catch a stale shape file immediately.
    """
    failures = []

    # 1. Every node carries a label this shape knows about. An unlabelled or
    #    unknown-labelled node would otherwise be silently treated as a
    #    non-step and skip required-attribute checks entirely.
    known = shape.step_labels | shape.branch_labels
    unknown_nodes = []
    for node, data in graph.nodes(data=True):
        labels = shape.labels_of(data)
        if not labels:
            unknown_nodes.append(f"{node!r} (no labels attribute)")
        elif not labels & known:
            unknown_nodes.append(f"{node!r} (labelled {sorted(labels)})")
    if unknown_nodes:
        failures.append(
            f"node(s) match no declared label {sorted(known)}: "
            f"{sorted(unknown_nodes)}"
        )

    # 2. A node labelled both step and branch is ambiguous.
    for node, data in graph.nodes(data=True):
        if shape.is_step_node(data) and shape.is_branch_node(data):
            failures.append(f"node {node!r} carries both a step and a branch label")

    # 3. Every declared branch rel actually appears. A typo'd rel type would
    #    otherwise mean "no branches exist" and quietly disable branch checks.
    present_rels = {data.get("rel") for _, _, data in graph.edges(data=True)}
    absent = shape.branch_rels - present_rels
    if absent:
        failures.append(
            f"declared branch_rels {sorted(absent)} appear on no edge in this "
            f"graph; present relationship types are {sorted(r for r in present_rels if r)}"
        )

    # 4. Branch nodes are reached only by branch rels, and branch rels lead
    #    only to branch nodes. This is the structural claim collapse_steps()
    #    relies on; it used to be *derived*, which is what let a mislabelled
    #    node get silently deleted.
    for src, dst, data in graph.edges(data=True):
        src_is_branch = shape.is_branch_node(graph.nodes[src])
        dst_is_branch = shape.is_branch_node(graph.nodes[dst])
        edge_is_branch = shape.is_branch_edge(data)
        if edge_is_branch and not dst_is_branch:
            failures.append(
                f"branch edge {src!r} -{data.get('rel')}-> {dst!r} does not lead "
                "to a node with a branch label"
            )
        if dst_is_branch and not edge_is_branch:
            failures.append(
                f"branch node {dst!r} is reached by non-branch edge {src!r} "
                f"-{data.get('rel')}-> {dst!r}"
            )
        if src_is_branch and edge_is_branch:
            failures.append(
                f"branch node {src!r} has an outgoing branch edge to {dst!r}; "
                "branch points may not chain"
            )

    # 5. Every branch node resolves to exactly one step. Checked here, up
    #    front, rather than being discovered mid-collapse.
    for node, data in graph.nodes(data=True):
        if not shape.is_branch_node(data):
            continue
        children = list(graph.successors(node))
        if len(children) != 1:
            failures.append(
                f"branch node {node!r} must have exactly one outgoing edge to a "
                f"step, found {sorted(children)}"
            )
        if graph.in_degree(node) == 0:
            failures.append(f"branch node {node!r} has no incoming edge")

    # 6. If a condition is declared, the attributes must actually be there.
    if shape.has_condition():
        for src, dst, data in graph.edges(data=True):
            if not shape.is_branch_edge(data):
                continue
            missing = [
                a
                for a in (shape.condition_key_attr, shape.condition_value_attr)
                if a not in data
            ]
            if missing:
                failures.append(
                    f"branch edge {src!r} -> {dst!r} missing declared condition "
                    f"attribute(s) {missing}"
                )

    return failures
