import anthropic
from dotenv import load_dotenv
from graph.neo4j_client import Neo4jClient
from models.types import TraversalStep, QueryResult

load_dotenv(override=True)
_client = anthropic.Anthropic()

ANSWER_SYSTEM = """You are a knowledge graph question answering agent.
You are given a user query and a subgraph of relevant entities and relationships
retrieved by graph traversal. Answer the query using only the provided graph context.

Be precise. If the graph context doesn't contain enough information, say so clearly.
Do not hallucinate facts not present in the graph."""


def generate_answer(
    query: str,
    retrieved_nodes: list[dict],
    traversal_steps: list[TraversalStep],
    hops_taken: int,
    graph: Neo4jClient,
) -> QueryResult:
    """Generate final answer from retrieved subgraph context"""
    node_ids = list({n.get("to_id") or n.get("id") for n in retrieved_nodes if n.get("to_id") or n.get("id")})
    subgraph = graph.get_subgraph(node_ids)

    context = "\n".join(
        f"({row['n.name']}) --[{row['r.type']}]--> ({row['m.name']})"
        + (f": {row['r.description']}" if row.get("r.description") else "")
        for row in subgraph
    )

    if not context:
        context = "(no relationships found for retrieved nodes)"

    response = _client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        system=ANSWER_SYSTEM,
        messages=[{
            "role": "user",
            "content": f"Query: {query}\n\nGraph context:\n{context}",
        }],
    )

    return QueryResult(
        answer=response.content[0].text,
        reasoning_path=traversal_steps,
        nodes_explored=len(retrieved_nodes),
        nodes_retrieved=len(node_ids),
        hops_taken=hops_taken,
    )
