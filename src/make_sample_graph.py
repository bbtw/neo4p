"""
Build a small sample planning graph and write it as a snapshot.

This stands in for snapshot.py when you don't have Neo4j to hand, so the
validation pipeline can be run and understood end to end:

    python make_sample_graph.py
    python validate.py snapshots/sample/graph.graphml expectations.yaml
"""

from pathlib import Path

import networkx as nx

TASKS = {
    "emergency_fund": ("Liquidity before anything illiquid or locked up", "policy_v4.2"),
    "pay_down_high_interest": ("Guaranteed return equal to the interest rate", "policy_v4.2"),
    "employer_match_401k": ("Match is an immediate 100% return", "policy_v4.2"),
    "roth_ira": ("Tax-free growth once the match is captured", "policy_v4.2"),
    "taxable_brokerage": ("Overflow once tax-advantaged space is used", "policy_v4.2"),
    "estate_review": ("Beneficiary and titling review", "policy_v4.2"),
}

# (source_task, target_task, condition_key, condition_value, criteria_description)
# Each entry becomes source_task -CRITERIA_BRANCH-> criteria node -HAS_CHILD-> target_task.
# Branches out of the same task share a condition_key with different values, so
# exactly one branch can ever match a client profile.
BRANCHES = [
    (
        "emergency_fund",
        "pay_down_high_interest",
        "fund_status",
        "funded_with_debt",
        "Does the client have an emergency fund on hand, but is still carrying high-interest debt?",
    ),
    (
        "emergency_fund",
        "employer_match_401k",
        "fund_status",
        "funded_clear",
        "Does the client have an emergency fund on hand and no high-interest debt?",
    ),
    (
        "pay_down_high_interest",
        "employer_match_401k",
        "debt_cleared",
        "yes",
        "Has the client's high-interest debt been paid off?",
    ),
    (
        "employer_match_401k",
        "roth_ira",
        "next_vehicle",
        "roth",
        "Is a Roth IRA the client's next investment vehicle?",
    ),
    (
        "employer_match_401k",
        "taxable_brokerage",
        "next_vehicle",
        "taxable",
        "Is a taxable brokerage account the client's next investment vehicle?",
    ),
    (
        "roth_ira",
        "taxable_brokerage",
        "after_roth",
        "invest",
        "After the Roth IRA, does the client want to keep investing?",
    ),
    (
        "roth_ira",
        "estate_review",
        "after_roth",
        "estate",
        "After the Roth IRA, is the client ready for an estate review?",
    ),
]


def build() -> nx.DiGraph:
    graph = nx.DiGraph()
    for task, (rationale, source_doc) in TASKS.items():
        graph.add_node(task, labels="Task", rationale=rationale, source_doc=source_doc)

    for src, dst, key, value, description in BRANCHES:
        criterion = f"{src}__{value}"
        graph.add_node(criterion, labels="CriteriaNode", description=description)
        graph.add_edge(
            src, criterion, rel="CRITERIA_BRANCH", condition_key=key, condition_value=value
        )
        graph.add_edge(criterion, dst, rel="HAS_CHILD")

    return graph


if __name__ == "__main__":
    outdir = Path("snapshots/sample")
    outdir.mkdir(parents=True, exist_ok=True)
    nx.write_graphml(build(), outdir / "graph.graphml")
    print(f"wrote {outdir / 'graph.graphml'}")
