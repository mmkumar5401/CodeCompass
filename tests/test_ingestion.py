import asyncio
import pytest
from unittest.mock import patch, MagicMock
from models.types import Triple, Entity, Relation
from ingestion.chunker import chunk_text
from ingestion.graph_writer import write_triples


def _make_triple(from_name: str, rel: str, to_name: str) -> Triple:
    import uuid
    e_from = Entity(id=str(uuid.uuid4()), name=from_name, type="Concept")
    e_to = Entity(id=str(uuid.uuid4()), name=to_name, type="Concept")
    r = Relation(from_id=e_from.id, to_id=e_to.id, type=rel)
    return Triple(e_from, r, e_to)


class TestChunker:
    def test_chunk_text_basic(self):
        text = "a" * 2000
        chunks = chunk_text(text, chunk_size=800, overlap=100)
        assert len(chunks) > 1
        assert all(len(c) <= 800 for c in chunks)

    def test_chunk_text_overlap(self):
        text = "x" * 1000
        chunks = chunk_text(text, chunk_size=500, overlap=100)
        # second chunk should start 400 chars in, so chunks[0][400:500] == chunks[1][:100]
        assert chunks[0][400:500] == chunks[1][:100]

    def test_chunk_text_short_input(self):
        text = "hello world"
        chunks = chunk_text(text, chunk_size=800, overlap=100)
        assert chunks == ["hello world"]


class TestGraphWriter:
    def test_deduplication(self):
        triple = _make_triple("A", "CAUSES", "B")
        mock_client = MagicMock()
        written = write_triples(mock_client, [triple, triple, triple])
        assert written == 1
        assert mock_client.write_triple.call_count == 1

    def test_distinct_triples_all_written(self):
        triples = [
            _make_triple("A", "CAUSES", "B"),
            _make_triple("B", "DEPENDS_ON", "C"),
            _make_triple("C", "HAS_COMPONENT", "D"),
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
