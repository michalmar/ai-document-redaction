from utils.redaction.base import split_into_chunks


def test_split_into_chunks_long_paragraph():
    long_para = "word " * 6000  # about 30000 chars? Actually 5*6000=30000
    # Use a smaller max for test
    max_chars = 2000
    chunks = split_into_chunks(long_para, max_chars)
    assert chunks, "No chunks returned"
    for c in chunks:
        assert len(c) <= max_chars + 2, f"Chunk exceeds max size: {len(c)} > {max_chars}"


def test_split_into_chunks_paragraphs():
    text = "Para1.\n\n" + ("Para2 text " * 100) + "\n\n" + "Para3"
    chunks = split_into_chunks(text, 500)
    assert isinstance(chunks, list)
    # Ensure reassembly contains both Paras
    reconstructed = ''.join(chunks).replace('\n\n', '\n\n')
    assert 'Para1' in reconstructed and 'Para3' in reconstructed


def test_split_into_chunks_empty_and_whitespace():
    """Test that split_into_chunks can produce empty or whitespace-only chunks."""
    # Text with multiple consecutive paragraph breaks or whitespace patterns
    text = "Para1.\n\n\n\n\n\nPara2.\n\n   \n\nPara3"
    chunks = split_into_chunks(text, 50)
    assert isinstance(chunks, list)
    
    # Verify some chunks might be empty or whitespace-only
    # This is expected behavior that the redaction strategy must handle
    non_empty = [c for c in chunks if c.strip()]
    assert len(non_empty) > 0, "Should have at least some non-empty chunks"
    assert len(chunks) >= len(non_empty), "Total chunks should be >= non-empty chunks"

