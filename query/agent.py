from config import neo4j_config
from graph.neo4j_client import Neo4jClient
from query.navigator_agent import navigate
from query.answer_agent import generate_answer


def _get_graph_client() -> Neo4jClient:
    cfg = neo4j_config()
    return Neo4jClient(uri=cfg["uri"], user=cfg["user"], password=cfg["password"])


def run_agent(question: str) -> "QueryResult":
    from models.types import QueryResult
    graph = _get_graph_client()
    try:
        retrieved_nodes, traversal_steps, hops_taken = navigate(question, graph)
        if not retrieved_nodes:
            return QueryResult(
                answer="No relevant information found in the knowledge graph.",
                reasoning_path=[],
                nodes_explored=0,
                nodes_retrieved=0,
                hops_taken=0,
            )
        return generate_answer(question, retrieved_nodes, traversal_steps, hops_taken, graph)
    finally:
        graph.close()
