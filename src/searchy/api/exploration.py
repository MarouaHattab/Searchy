from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import Field, field_validator, model_validator

from searchy.core.config import Settings
from searchy.domain import Record

GraphNodeType = Literal[
    "Scene",
    "Video",
    "Episode",
    "Observation",
    "Dialogue",
    "Character",
    "Clothing",
    "Action",
    "Object",
    "Location",
]
GraphEdgeType = Literal[
    "PART_OF",
    "HAS_OBSERVATION",
    "HAS_DIALOGUE",
    "DESCRIBES",
    "SUBJECT",
    "CONTAINS",
    "OCCURS_AT",
    "APPEARS_IN",
    "SPOKEN_BY",
]


class GraphRequest(Record):
    scene_ids: list[str] = Field(min_length=1, max_length=12)
    collection_id: str | None = Field(default=None, min_length=1, max_length=80)
    max_nodes: int = Field(default=150, ge=1, le=300)
    max_edges: int = Field(default=240, ge=1, le=500)
    evidence_ids: list[str] = Field(default_factory=list, max_length=120)

    @field_validator("scene_ids")
    @classmethod
    def unique_scene_ids(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or len(item) > 100 for item in value):
            raise ValueError("Scene identifiers must be nonempty and at most 100 characters")
        if len(set(value)) != len(value):
            raise ValueError("Scene identifiers must be unique")
        return value

    @model_validator(mode="after")
    def enough_seed_nodes(self):
        if self.max_nodes < len(self.scene_ids):
            raise ValueError("max_nodes must accommodate every requested scene")
        return self


class GraphNode(Record):
    id: str
    type: GraphNodeType
    label: str
    scene_ids: list[str]
    properties: dict[str, str | int | float | bool | None]
    evidence: list[str] = Field(default_factory=list)
    start: float | None = None
    end: float | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    verified: bool | None = None


class GraphEdge(Record):
    id: str
    source: str
    target: str
    type: GraphEdgeType
    scene_ids: list[str]
    evidence: list[str] = Field(default_factory=list)
    derived: Literal[False] = False


class GraphResponse(Record):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool
    scene_ids: list[str]
    warnings: list[str]


def create_exploration_router(settings: Settings, services, authorize) -> APIRouter:
    from searchy.graph.explorer import GraphExplorer

    router = APIRouter(prefix="/api", dependencies=[Depends(authorize)])

    @router.post("/search/graph", response_model=GraphResponse)
    def graph(body: GraphRequest, svc=Depends(services)):
        return GraphExplorer(svc.graph, svc.metadata).explore(body)

    return router
