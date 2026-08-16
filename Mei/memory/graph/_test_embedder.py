import pytest
from unittest.mock import patch, MagicMock
from Mei.memory.graph.embedder import embed

@patch("Mei.memory.graph.embedder.get_config")
def test_embed_dimensions_and_similarity(mock_get_config):
    """
    Tests: 
    - embed("open chrome") returns length-384 list. 
    - Dot product of "open chrome" and "launch chrome" > 0.8. 
    - embed("") does not raise.
    """
    # Mock config to enforce the 384-dim standard model
    mock_config = MagicMock()
    mock_config.kuzu.embedding_model = "all-MiniLM-L6-v2"
    mock_get_config.return_value = mock_config

    # 1. embed("open chrome") returns length-384 list
    emb1 = embed("open chrome")
    assert isinstance(emb1, list)
    assert len(emb1) == 384

    # 2. Dot product of "open chrome" and "launch chrome" > 0.8
    emb2 = embed("launch chrome")
    dot_product = sum(a * b for a, b in zip(emb1, emb2))
    assert dot_product > 0.8, f"Expected similarity > 0.8, got {dot_product}"

    # 3. embed("") does not raise
    try:
        emb_empty = embed("")
        assert isinstance(emb_empty, list)
        assert len(emb_empty) == 384
    except Exception as e:
        pytest.fail(f"embed('') raised an unexpected exception: {e}")