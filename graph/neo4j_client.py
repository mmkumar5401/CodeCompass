import uuid
from datetime import datetime, timezone
from neo4j import GraphDatabase
from models.types import Triple


class Neo4jClient:
    def __init__(self, uri: str, user: str, password: str):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def write_triple(self, triple: Triple, session_id: str = "ingestion"):
        """MERGE entities and relationship — idempotent.
        Tags each relationship with session_id and created_at on first write."""
        with self.driver.session() as session:
            session.run("""
                MERGE (a:Entity {id: $from_id})
                SET a.name = $from_name, a.type = $from_type
                MERGE (b:Entity {id: $to_id})
                SET b.name = $to_name, b.type = $to_type
                MERGE (a)-[r:RELATION {type: $rel_type}]->(b)
                SET r.weight = $weight, r.description = $rel_desc,
                    r.session_id = coalesce(r.session_id, $session_id),
                    r.created_at = coalesce(r.created_at, $created_at)
            """, {
                "from_id": triple.entity_from.id,
                "from_name": triple.entity_from.name,
                "from_type": triple.entity_from.type,
                "to_id": triple.entity_to.id,
                "to_name": triple.entity_to.name,
                "to_type": triple.entity_to.type,
                "rel_type": triple.relation.type,
                "weight": triple.relation.weight,
                "rel_desc": triple.relation.description,
                "session_id": session_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })

    def remember_triple(self, from_name: str, rel_type: str, to_name: str, session_id: str):
        """
        Write a new fact discovered by the model mid-session.
        Entities are MERGE'd (created if absent, type defaults to Concept).
        Relationship is tagged with session_id + created_at so it can be
        scoped, aged, or forgotten independently of ingested facts.
        """
        from_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, from_name.lower()))
        to_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, to_name.lower()))
        with self.driver.session() as session:
            session.run("""
                MERGE (a:Entity {id: $from_id})
                ON CREATE SET a.name = $from_name, a.type = 'Concept'
                MERGE (b:Entity {id: $to_id})
                ON CREATE SET b.name = $to_name, b.type = 'Concept'
                MERGE (a)-[r:RELATION {type: $rel_type}]->(b)
                ON CREATE SET r.weight    = 1.0,
                              r.session_id = $session_id,
                              r.created_at = $created_at,
                              r.source     = 'agent'
            """, {
                "from_id": from_id,
                "from_name": from_name,
                "to_id": to_id,
                "to_name": to_name,
                "rel_type": rel_type.upper().replace(" ", "_"),
                "session_id": session_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })

    def merge_nodes(self, canonical_id: str, canonical_name: str, duplicate_ids: list[str]):
        """
        Merge duplicate nodes into the canonical node.
        Re-points all relationships, then detach-deletes each duplicate.
        Does not use APOC — works on any Neo4j instance.
        """
        with self.driver.session() as session:
            for dup_id in duplicate_ids:
                # Re-point outgoing rels from duplicate → canonical
                session.run("""
                    MATCH (dup:Entity {id: $dup_id})-[r:RELATION]->(target:Entity)
                    WHERE target.id <> $canonical_id
                    MERGE (c:Entity {id: $canonical_id})-[nr:RELATION {type: r.type}]->(target)
                    ON CREATE SET nr.weight     = r.weight,
                                  nr.description = r.description,
                                  nr.session_id  = r.session_id,
                                  nr.created_at  = r.created_at
                """, {"dup_id": dup_id, "canonical_id": canonical_id})

                # Re-point incoming rels from duplicate ← canonical
                session.run("""
                    MATCH (source:Entity)-[r:RELATION]->(dup:Entity {id: $dup_id})
                    WHERE source.id <> $canonical_id
                    MERGE (source)-[nr:RELATION {type: r.type}]->(c:Entity {id: $canonical_id})
                    ON CREATE SET nr.weight     = r.weight,
                                  nr.description = r.description,
                                  nr.session_id  = r.session_id,
                                  nr.created_at  = r.created_at
                """, {"dup_id": dup_id, "canonical_id": canonical_id})

                # Delete the duplicate (DETACH handles any lingering rels)
                session.run("""
                    MATCH (dup:Entity {id: $dup_id})
                    DETACH DELETE dup
                """, {"dup_id": dup_id})

            # Ensure canonical node name is up to date
            session.run("""
                MATCH (c:Entity {id: $canonical_id})
                SET c.name = $canonical_name
            """, {"canonical_id": canonical_id, "canonical_name": canonical_name})

    def get_neighbours(self, node_ids: list[str], exclude_ids: list[str] = None) -> list[dict]:
        """Get all direct neighbours of a set of nodes, optionally excluding already-visited IDs."""
        exclude = list(exclude_ids or [])
        with self.driver.session() as session:
            result = session.run("""
                MATCH (n:Entity)-[r:RELATION]->(m:Entity)
                WHERE n.id IN $node_ids
                  AND NOT m.id IN $exclude
                RETURN n.id AS from_id, n.name AS from_name, n.type AS from_type,
                       r.type AS rel_type, r.weight AS weight,
                       m.id AS to_id, m.name AS to_name, m.type AS to_type
            """, {"node_ids": node_ids, "exclude": exclude})
            return [record.data() for record in result]

    def get_all_node_names(self) -> list[dict]:
        """Return id, name, type for every node — used by seed finder to ground LLM selection."""
        with self.driver.session() as session:
            result = session.run(
                "MATCH (n:Entity) RETURN n.id AS id, n.name AS name, n.type AS type ORDER BY n.name"
            )
            return [record.data() for record in result]

    def find_nodes_by_name(self, names: list[str]) -> list[dict]:
        """Fuzzy match node names for seed finding"""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (n:Entity)
                WHERE any(name IN $names WHERE toLower(n.name) CONTAINS toLower(name))
                RETURN n.id AS id, n.name AS name, n.type AS type
                LIMIT 10
            """, {"names": names})
            return [record.data() for record in result]

    def get_2hop_neighbours(self, node_ids: list[str], exclude_ids: list[str] = None) -> list[dict]:
        """
        Fetch hop-1 neighbours and their hop-2 children in a single query.
        Returns flat rows; group by hop1_id in Python to reconstruct the tree.
        """
        exclude = list(exclude_ids or [])
        with self.driver.session() as session:
            result = session.run("""
                MATCH (n:Entity)-[r1:RELATION]->(m:Entity)
                WHERE n.id IN $node_ids
                  AND NOT m.id IN $exclude
                OPTIONAL MATCH (m)-[r2:RELATION]->(k:Entity)
                WHERE NOT k.id IN $exclude
                  AND k.id <> n.id
                RETURN n.id   AS source_id,  n.name AS source_name,
                       m.id   AS hop1_id,    m.name AS hop1_name,
                       m.type AS hop1_type,  r1.type AS rel1_type,
                       k.id   AS hop2_id,    k.name AS hop2_name,
                       k.type AS hop2_type,  r2.type AS rel2_type
            """, {"node_ids": node_ids, "exclude": exclude})
            return [record.data() for record in result]

    def get_subgraph(self, node_ids: list[str]) -> list[dict]:
        """Retrieve full context for a set of nodes"""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (n:Entity)-[r:RELATION]->(m:Entity)
                WHERE n.id IN $node_ids OR m.id IN $node_ids
                RETURN n.name, r.type, m.name, r.description
            """, {"node_ids": node_ids})
            return [record.data() for record in result]

    def get_all_edges(self) -> list[dict]:
        """Return every edge in the graph as compact dicts for full-graph context."""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (n:Entity)-[r:RELATION]->(m:Entity)
                RETURN n.name AS from_name, n.type AS from_type,
                       r.type AS rel_type, r.description AS rel_desc,
                       m.name AS to_name, m.type AS to_type
            """)
            return [record.data() for record in result]

    def node_count(self) -> int:
        with self.driver.session() as session:
            result = session.run("MATCH (n:Entity) RETURN count(n) AS cnt")
            return result.single()["cnt"]

    def close(self):
        self.driver.close()
