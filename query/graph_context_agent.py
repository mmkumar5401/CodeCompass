import anthropic
import json
from dotenv import load_dotenv
from graph.neo4j_client import Neo4jClient
from models.types import QueryResult

load_dotenv(override=True)
_client = anthropic.Anthropic()

ANSWER_SYSTEM = """You are a knowledge graph question answering agent.
You are given the complete knowledge graph as a list of edges and a user query.
Answer the query using only the relationships present in the graph.

Be precise. If the graph doesn't contain enough information, say so clearly.
Do not hallucinate facts not present in the graph."""


def _build_graph_text(edges: list[dict]) -> str:
    lines = []
    for e in edges:
        line = f"({e['from_name']}:{e['from_type']}) --[{e['rel_type']}]--> ({e['to_name']}:{e['to_type']})"
        if e.get("rel_desc"):
            line += f" // {e['rel_desc']}"
        lines.append(line)
    return "\n".join(lines)


def run_full_graph_agent(question: str, graph: Neo4jClient) -> QueryResult:
    """
    Answer a query by sending the entire graph to the model in one call.

    The graph is passed as a cached system block so repeated queries within
    5 minutes reuse the cached tokens (~10x cheaper after the first call).
    """
    edges = graph.get_all_edges()
    if not edges:
        return QueryResult(
            answer="The knowledge graph is empty. Please ingest documents first.",
            reasoning_path=[],
            nodes_explored=0,
            nodes_retrieved=0,
            hops_taken=0,
        )

    graph_text = f"Knowledge graph ({len(edges)} edges):\n\n" + _build_graph_text(edges)

    response = _client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        system=[
            {
                "type": "text",
                "text": graph_text,
                "cache_control": {"type": "ephemeral"},
            },
            {
                "type": "text",
                "text": ANSWER_SYSTEM,
            },
        ],
        messages=[{"role": "user", "content": question}],
    )

    # Count unique node names as a proxy for graph size
    node_names = {e["from_name"] for e in edges} | {e["to_name"] for e in edges}

    return QueryResult(
        answer=response.content[0].text,
        reasoning_path=[],
        nodes_explored=len(node_names),
        nodes_retrieved=len(node_names),
        hops_taken=0,
    )
