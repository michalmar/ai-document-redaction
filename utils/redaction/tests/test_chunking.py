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
