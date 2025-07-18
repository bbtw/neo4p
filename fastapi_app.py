from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
import os
from neo4j_dao import Neo4jDAO

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Init DAO
dao = Neo4jDAO(os.getenv("NEO4J_URI"),os.getenv("NEO4J_USER"),os.getenv("NEO4J_PASSWORD"))

class RelationshipCreate(BaseModel):
    source: str
    target: str
    rel_type: str

@app.get("/api/relationship-types")
def get_relationship_types():
    return dao.get_relationship_types()

@app.get("/api/graph")
def get_graph(subneed: Optional[str] = None):
    return dao.get_graph(subneed=subneed)

@app.post("/api/relationships")
def create_relationship(rel: RelationshipCreate):
    try:
        return dao.create_relationship(rel.source, rel.target, rel.rel_type)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
