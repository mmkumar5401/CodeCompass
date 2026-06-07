from models.types import TraversalStep


def format_traversal_steps(steps: list[TraversalStep]) -> str:
    """Human-readable summary of a reasoning path"""
    if not steps:
        return "(no traversal steps)"
    lines = []
    for i, step in enumerate(steps, 1):
        score = f"{step.relevance_score:.2f}"
        lines.append(
            f"  {i}. [{step.relation_type}] → {step.node_name} "
            f"(score={score}): {step.reasoning}"
        )
    return "\n".join(lines)


def format_subgraph_rows(rows: list[dict]) -> str:
    """Format Neo4j subgraph rows for LLM prompts"""
    return "\n".join(
        f"({row['n.name']}) --[{row['r.type']}]--> ({row['m.name']})"
        + (f": {row['r.description']}" if row.get("r.description") else "")
        for row in rows
    )
