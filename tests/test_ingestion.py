import pytest
from unittest.mock import patch, MagicMock
from ingestion.graph_writer import write_triples
from models.code_types import CodeTriple


def _make_triple(from_entity: str, rel: str, to_entity: str) -> CodeTriple:
    return CodeTriple(
        from_entity=from_entity,
        from_type="function",
        relation_type=rel,
        to_entity=to_entity,
        to_type="function",
        source_file="test.py",
        line_number=1,

class TestGraphWriter:
    def test_deduplication(self):
        triple = _make_triple("A", "CALLS", "B")
        mock_client = MagicMock()
        written = write_triples(mock_client, [triple, triple, triple])
        assert written == 1
        assert mock_client.write_code_triple.call_count == 1

    def test_distinct_triples_all_written(self):
        triples = [
            _make_triple("A", "CALLS", "B"),
            _make_triple("B", "IMPORTS", "C"),
            _make_triple("C", "INHERITS", "D"),
        ]
        mock_client = MagicMock()
        written = write_triples(mock_client, triples)
        assert written == 3


class TestReaderAgent:
    @patch("ingestion.reader_agent._client")
    def test_extract_triples_valid_response(self, mock_client):
        from ingestion.reader_agent import _extract_triples_sync

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"entities": [{"name": "Python", "type": "System", "description": "lang"}, {"name": "Django", "type": "System", "description": "framework"}], "relations": [{"from": "Django", "to": "Python", "type": "BUILT_ON", "weight": 0.95, "description": "Django is built on Python"}]}')]
        mock_client.messages.create.return_value = mock_response

        triples = _extract_triples_sync("Django is a web framework built on Python.")
        assert len(triples) == 1
        assert triples[0].relation.type == "BUILT_ON"
        assert triples[0].entity_from.name == "Django"
        assert triples[0].entity_to.name == "Python"

    @patch("ingestion.reader_agent._client")
    def test_extract_triples_bad_json(self, mock_client):
        from ingestion.reader_agent import _extract_triples_sync

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="not json at all")]
        mock_client.messages.create.return_value = mock_response

        triples = _extract_triples_sync("some text")
        assert triples == []

    @patch("ingestion.reader_agent._client")
    def test_extract_triples_missing_entity_skipped(self, mock_client):
        from ingestion.reader_agent import _extract_triples_sync

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"entities": [{"name": "A", "type": "Concept"}], "relations": [{"from": "A", "to": "MISSING", "type": "CAUSES", "weight": 0.9}]}')]
        mock_client.messages.create.return_value = mock_response

        triples = _extract_triples_sync("A causes something.")
        assert triples == []
