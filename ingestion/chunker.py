import PyPDF2


def chunk_pdf(filepath: str, chunk_size: int = 800, overlap: int = 100) -> list[str]:
    """Split PDF into overlapping text chunks"""
    with open(filepath, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        full_text = " ".join(
            page.extract_text() or "" for page in reader.pages
        )
    return _sliding_window(full_text, chunk_size, overlap)


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 100) -> list[str]:
    """Split plain text into overlapping chunks"""
    return _sliding_window(text, chunk_size, overlap)


def _sliding_window(text: str, chunk_size: int, overlap: int) -> list[str]:
    chunks = []
    start = 0
    step = chunk_size - overlap
    while start < len(text):
        chunks.append(text[start : start + chunk_size])
        start += step
    return chunks
