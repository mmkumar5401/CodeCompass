from unittest.mock import MagicMock, patch
from models.types import TraversalStep, QueryResult
from query.answer_agent import generate_answer


STEPS = [
    TraversalStep(node_id="n1", node_name="Node1", relation_type="CAUSES", relevance_score=0.9, reasoning="direct"),
    TraversalStep(node_id="n2", node_name="Node2", relation_type="DEPENDS_ON", relevance_score=0.7, reasoning="indirect"),
]

RETRIEVED_NODES = [
    {"id": "seed", "name": "Seed", "type": "Concept"},
    {"to_id": "n1", "to_name": "Node1", "to_type": "Concept", "rel_type": "CAUSES", "from_name": "Seed"},
]

SUBGRAPH_ROWS = [
    {"n.name": "Seed", "r.type": "CAUSES", "m.name": "Node1", "r.description": "direct cause"},
]


class TestAnswerAgent:
    @patch("query.answer_agent._client")
    def test_generate_answer_returns_result(self, mock_client):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="The answer is 42.")]
        mock_client.messages.create.return_value = mock_response

        mock_graph = MagicMock()
        mock_graph.get_subgraph.return_value = SUBGRAPH_ROWS

        result = generate_answer("What is the answer?", RETRIEVED_NODES, STEPS, 2, mock_graph)

        assert isinstance(result, QueryResult)
        assert result.answer == "The answer is 42."
        assert result.hops_taken == 2
        assert result.nodes_explored == len(RETRIEVED_NODES)

    @patch("query.answer_agent._client")
    def test_generate_answer_empty_subgraph(self, mock_client):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Insufficient context.")]
        mock_client.messages.create.return_value = mock_response

        mock_graph = MagicMock()
        mock_graph.get_subgraph.return_value = []

        result = generate_answer("A question", RETRIEVED_NODES, [], 1, mock_graph)
        # Should still call the LLM and return a result
        assert result.answer == "Insufficient context."
        assert result.reasoning_path == []
