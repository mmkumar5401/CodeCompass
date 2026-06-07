from unittest.mock import MagicMock, patch
from models.types import TraversalStep
from query.relevance_filter import filter_relevant_neighbours, FilterResult, RELEVANCE_THRESHOLD

# 1-hop rows as returned by Neo4jClient.get_neighbours (batched for multiple sources)
ROWS = [
    {"from_id": "seed", "from_name": "Seed", "rel_type": "CAUSES",
     "to_id": "n1", "to_name": "Node1", "to_type": "Concept", "weight": 1.0},
    {"from_id": "seed", "from_name": "Seed", "rel_type": "USED_BY",
     "to_id": "n2", "to_name": "Node2", "to_type": "System", "weight": 1.0},
]

ALL_RELEVANT_RESPONSE = '{"nodes": [{"node_id": "n1", "relevance_score": 0.9, "reasoning": "relevant"}, {"node_id": "n2", "relevance_score": 0.85, "reasoning": "relevant"}]}'
MIXED_RESPONSE = '{"nodes": [{"node_id": "n1", "relevance_score": 0.9, "reasoning": "relevant"}, {"node_id": "n2", "relevance_score": 0.2, "reasoning": "not relevant"}]}'
ALL_IRRELEVANT_RESPONSE = '{"nodes": [{"node_id": "n1", "relevance_score": 0.2, "reasoning": "no"}, {"node_id": "n2", "relevance_score": 0.1, "reasoning": "no"}]}'


class TestRelevanceFilter:
    @patch("query.relevance_filter._client")
    def test_all_relevant(self, mock_client):
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text=ALL_RELEVANT_RESPONSE)]
        )
        result = filter_relevant_neighbours("test query", ROWS, set())
        assert {n["to_id"] for n in result.to_collect} == {"n1", "n2"}
        assert len(result.pruned_ids) == 0

    @patch("query.relevance_filter._client")
    def test_mixed_relevance(self, mock_client):
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text=MIXED_RESPONSE)]
        )
        result = filter_relevant_neighbours("test query", ROWS, set())
        collected_ids = {n["to_id"] for n in result.to_collect}
        assert "n1" in collected_ids
        assert "n2" not in collected_ids
        assert "n2" in result.pruned_ids

    @patch("query.relevance_filter._client")
    def test_all_irrelevant(self, mock_client):
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text=ALL_IRRELEVANT_RESPONSE)]
        )
        result = filter_relevant_neighbours("test query", ROWS, set())
        assert result.to_collect == []
        assert result.to_expand == []
        assert "n1" in result.pruned_ids
        assert "n2" in result.pruned_ids

    @patch("query.relevance_filter._client")
    def test_visited_nodes_excluded(self, mock_client):
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text=ALL_RELEVANT_RESPONSE)]
        )
        result = filter_relevant_neighbours("test query", ROWS, {"n1"})
        collected_ids = {n["to_id"] for n in result.to_collect}
        assert "n1" not in collected_ids

    @patch("query.relevance_filter._client")
    def test_empty_rows_returns_empty(self, mock_client):
        result = filter_relevant_neighbours("test query", [], set())
        assert result.to_collect == []
        assert result.to_expand == []
        mock_client.messages.create.assert_not_called()


class TestNavigator:
    @patch("query.navigator_agent.find_seed_nodes")
    @patch("query.navigator_agent.filter_relevant_neighbours")
    def test_navigate_no_seeds(self, mock_filter, mock_seeds):
        from query.navigator_agent import navigate
        mock_seeds.return_value = []
        mock_graph = MagicMock()

        nodes, steps, depth = navigate("test query", mock_graph)
        assert nodes == []
        assert steps == []
        assert depth == 0

    @patch("query.navigator_agent.find_seed_nodes")
    @patch("query.navigator_agent.filter_relevant_neighbours")
    def test_navigate_batches_entire_frontier(self, mock_filter, mock_seeds):
        """get_neighbours is called once per layer, not once per frontier node."""
        from query.navigator_agent import navigate

        mock_seeds.return_value = [
            {"id": "seed1", "name": "Seed1", "type": "Concept"},
            {"id": "seed2", "name": "Seed2", "type": "Concept"},
        ]
        mock_graph = MagicMock()
        mock_graph.get_neighbours.return_value = []  # no neighbours → exits after 1 layer
        mock_filter.return_value = FilterResult([], [], set(), [])

        navigate("test query", mock_graph)

        # get_neighbours called once with both seed IDs, not twice
        assert mock_graph.get_neighbours.call_count == 1
        call_args = mock_graph.get_neighbours.call_args[0][0]
        assert set(call_args) == {"seed1", "seed2"}

    @patch("query.navigator_agent.find_seed_nodes")
    @patch("query.navigator_agent.filter_relevant_neighbours")
    def test_navigate_collects_relevant_nodes(self, mock_filter, mock_seeds):
        from query.navigator_agent import navigate

        mock_seeds.return_value = [{"id": "seed1", "name": "Seed", "type": "Concept"}]
        mock_graph = MagicMock()
        mock_graph.get_neighbours.return_value = ROWS

        relevant_node = {"to_id": "n1", "to_name": "Node1", "to_type": "Concept",
                         "rel_type": "CAUSES", "from_name": "Seed", "from_id": "seed1"}
        mock_filter.return_value = FilterResult(
            to_collect=[relevant_node],
            to_expand=[relevant_node],
            pruned_ids={"n2"},
            steps=[TraversalStep("n1", "Node1", "CAUSES", 0.9, "relevant")],
        )

        nodes, steps, depth = navigate("test query", mock_graph)
        collected_ids = {n.get("id") or n.get("to_id") for n in nodes}
        assert "n1" in collected_ids
        assert depth >= 1

    @patch("query.navigator_agent.find_seed_nodes")
    @patch("query.navigator_agent.filter_relevant_neighbours")
    def test_navigate_prunes_after_consecutive_misses(self, mock_filter, mock_seeds):
        from query.navigator_agent import navigate, MAX_CONSECUTIVE_MISSES

        mock_seeds.return_value = [{"id": "seed1", "name": "Seed", "type": "Concept"}]
        mock_graph = MagicMock()
        mock_graph.get_neighbours.return_value = ROWS
        mock_filter.return_value = FilterResult([], [], {"n1", "n2"}, [])

        nodes, steps, depth = navigate("test query", mock_graph)
        assert len(nodes) == 1  # only seed returned
        assert mock_filter.call_count <= MAX_CONSECUTIVE_MISSES
