from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from neo4j import GraphDatabase
from fastapi.responses import JSONResponse

app = FastAPI()

# Allow requests from Angular/Dash clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Neo4j connection
neo4j_driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "your_password"))

class RelationshipCreate(BaseModel):
    source: str
    target: str
    rel_type: str

@app.get("/api/relationship-types")
def get_relationship_types():
    return [
        {"label": "Has SubNeed", "value": "HAS_SUBNEED"},
        {"label": "Has Task", "value": "HAS_TASK"},
        {"label": "Related To", "value": "RELATED_TO"},
        {"label": "Depends On", "value": "DEPENDS_ON"}
    ]

@app.get("/api/graph")
def get_graph(subneed: Optional[str] = None):
    with neo4j_driver.session() as session:
        if subneed:
            result = session.run("""
                MATCH (n)-[r]->(m)
                WHERE m:SubNeed AND m.name = $subneed OR n:SubNeed AND n.name = $subneed
                RETURN DISTINCT n.name AS from, labels(n)[0] AS fromType,
                                type(r) AS rel, m.name AS to, labels(m)[0] AS toType
            """, subneed=subneed)
        else:
            result = session.run("""
                MATCH (n)-[r]->(m)
                RETURN DISTINCT n.name AS from, labels(n)[0] AS fromType,
                                type(r) AS rel, m.name AS to, labels(m)[0] AS toType
            """)

        nodes = set()
        edges = []
        for r in result:
            nodes.add((r['from'], r['fromType']))
            nodes.add((r['to'], r['toType']))
            edges.append({"data": {"source": r['from'], "target": r['to'], "label": r['rel']}})

        node_elements = [
            {
                "data": {"id": name, "label": name, "type": typ},
                "classes": typ.lower()
            }
            for name, typ in nodes
        ]
        return node_elements + edges

@app.post("/api/relationships")
def create_relationship(rel: RelationshipCreate):
    if rel.source == rel.target:
        return JSONResponse(status_code=400, content={"error": "Cannot create relationship to self."})
    with neo4j_driver.session() as session:
        cypher = """
            MATCH (a {name: $source}), (b {name: $target})
            MERGE (a)-[r:%s]->(b)
        """ % rel.rel_type.upper()
        session.run(cypher, source=rel.source, target=rel.target)
    return {
        "status": "relationship created",
        "source": rel.source,
        "target": rel.target,
        "type": rel.rel_type
    }

