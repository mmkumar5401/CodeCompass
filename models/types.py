from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Entity:
    id: str
    name: str
    type: str                        # Person, Concept, Place, Event, etc.
    description: Optional[str] = None
    source_chunk: Optional[str] = None


@dataclass
class Relation:
    from_id: str
    to_id: str
    type: str                        # HAS_COMPONENT, CAUSES, DEPENDS_ON, etc.
    weight: float = 1.0              # Confidence/strength 0–1
    description: Optional[str] = None


@dataclass
class Triple:
    entity_from: Entity
    relation: Relation
    entity_to: Entity


@dataclass
class TraversalStep:
    node_id: str
    node_name: str
    relation_type: str
    relevance_score: float
    reasoning: str                   # Why the agent followed this edge


@dataclass
class QueryResult:
    answer: str
    reasoning_path: list[TraversalStep]
    nodes_explored: int
    nodes_retrieved: int
    hops_taken: int
