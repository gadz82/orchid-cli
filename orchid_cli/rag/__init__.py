"""
Register the ChromaDB vector backend for orchid-cli.

Importing this module (``import orchid_cli.rag``) registers ``"chroma"`` in
the library's ``VECTOR_BACKEND_REGISTRY`` so ``vector_backend="chroma"``
resolves normally via ``build_reader()``.
"""

from __future__ import annotations

import os

from orchid_ai.rag.factory import register_vector_backend


def _build_chroma_reader(
    *,
    embedding_model: str = "text-embedding-3-small",
    **_settings: object,
) -> object:
    from orchid_ai.rag.embeddings import build_embeddings, get_embedding_dimension
    from orchid_cli.rag.backends.chroma import ChromaRepository

    chroma_path = os.environ.get("CHROMA_PATH", "~/.orchid/chroma")
    embeddings = build_embeddings(embedding_model)
    dimension = get_embedding_dimension(embedding_model)
    return ChromaRepository(
        path=chroma_path,
        embeddings=embeddings,
        embedding_dimension=dimension,
    )


register_vector_backend("chroma", _build_chroma_reader)
