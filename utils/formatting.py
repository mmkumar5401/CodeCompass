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
