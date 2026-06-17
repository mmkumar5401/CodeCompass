FROM python:3.10-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    anthropic>=0.40.0 \
    neo4j>=5.18.0 \
    pypdf2>=3.0.0 \
    python-dotenv>=1.0.0 \
    rich>=13.0.0 \
    tqdm>=4.66.0 \
    tree-sitter>=0.21.0 \
    tree-sitter-python>=0.21.0 \
    tree-sitter-javascript>=0.21.0 \
    tree-sitter-typescript>=0.21.0 \
    tree-sitter-html>=0.21.0 \
    tree-sitter-css>=0.21.0 \
    watchdog>=4.0.0 \
    mcp

COPY graph/ ./graph/
COPY ingestion/ ./ingestion/
COPY models/ ./models/
COPY main.py config.py ./

ENV NEO4J_URI=bolt://localhost:7687
ENV NEO4J_USER=neo4j
ENV NEO4J_PASSWORD=password123

ENTRYPOINT ["python", "-m", "graph.mcp_server", "sse", "8000"]
