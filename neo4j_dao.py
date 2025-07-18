from neo4j import GraphDatabase
from typing import List, Dict, Optional

class Neo4jDAO:
    def __init__(self, uri: str, user: str, password: str):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self.driver.close()

    def get_relationship_types(self) -> List[Dict[str, str]]:
        return [
            {"label": "Has SubNeed", "value": "HAS_SUBNEED"},
            {"label": "Has Task", "value": "HAS_TASK"},
            {"label": "Related To", "value": "RELATED_TO"},
            {"label": "Depends On", "value": "DEPENDS_ON"}
        ]

    def get_graph(self, subneed: Optional[str] = None) -> List[Dict]:
        with self.driver.session() as session:
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
                    "data": {"id": name, "label": name},
                    "classes": typ.lower()
                }
                for name, typ in nodes
            ]
            return node_elements + edges

    def create_relationship(self, source: str, target: str, rel_type: str) -> Dict:
        if source == target:
            raise ValueError("Cannot create relationship to self.")
        with self.driver.session() as session:
            cypher = f"""
                MATCH (a {{name: $source}}), (b {{name: $target}})
                MERGE (a)-[r:{rel_type.upper()}]->(b)
            """
            session.run(cypher, source=source, target=target)
        return {"status": "relationship created", "source": source, "target": target, "type": rel_type}
