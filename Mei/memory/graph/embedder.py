from sentence_transformers import SentenceTransformer
from ...core.config import get_config
from typing import Optional

_model = None

def get_embedder() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(get_config().kuzu.embedding_model,device="cpu")
    return _model

def embed(text: str)-> list:
    """Returns a 384 dim normalized float list. Never raises."""
    try:
        return get_embedder().encode(text, normalize_embeddings=True).tolist()
    except Exception as e:
        print(f"[Embedder] Failed: {e}")
        return [0.0]*384

    

