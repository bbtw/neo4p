"""
Build a small sample planning graph and write it as a snapshot.

This stands in for snapshot.py when you don't have Neo4j to hand, so the
validation pipeline can be run and understood end to end:

    python make_sample_graph.py
    python validate.py snapshots/sample/graph.graphml expectations.yaml
"""

from pathlib import Path

import networkx as nx

STEPS = {
    "emergency_fund": ("Liquidity before anything illiquid or locked up", "policy_v4.2"),
    "pay_down_high_interest": ("Guaranteed return equal to the interest rate", "policy_v4.2"),
    "employer_match_401k": ("Match is an immediate 100% return", "policy_v4.2"),
    "roth_ira": ("Tax-free growth once the match is captured", "policy_v4.2"),
    "taxable_brokerage": ("Overflow once tax-advantaged space is used", "policy_v4.2"),
    "estate_review": ("Beneficiary and titling review", "policy_v4.2"),
}

# (source, target, condition_key, condition_value)
# Edges out of the same node share a condition_key with different values, so
# exactly one branch can ever match a client profile.
TRANSITIONS = [
    ("emergency_fund", "pay_down_high_interest", "fund_status", "funded_with_debt"),
    ("emergency_fund", "employer_match_401k", "fund_status", "funded_clear"),
    ("pay_down_high_interest", "employer_match_401k", "debt_cleared", "yes"),
    ("employer_match_401k", "roth_ira", "next_vehicle", "roth"),
    ("employer_match_401k", "taxable_brokerage", "next_vehicle", "taxable"),
    ("roth_ira", "taxable_brokerage", "after_roth", "invest"),
    ("roth_ira", "estate_review", "after_roth", "estate"),
]


def build():
    graph = nx.DiGraph()
    for step, (rationale, source_doc) in STEPS.items():
        graph.add_node(step, rationale=rationale, source_doc=source_doc)
    for src, dst, key, value in TRANSITIONS:
        graph.add_edge(src, dst, rel="LEADS_TO", condition_key=key, condition_value=value)
    return graph


if __name__ == "__main__":
    outdir = Path("snapshots/sample")
    outdir.mkdir(parents=True, exist_ok=True)
    nx.write_graphml(build(), outdir / "graph.graphml")
    print(f"wrote {outdir / 'graph.graphml'}")
