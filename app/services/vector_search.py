"""
Vector Search Service
=====================
Handles embedding generation via OpenAI text-embedding-3-small (1536 dimensions)
and vector search using Qdrant. Includes graceful fallback for local/offline testing.
"""

import os
import logging
import hashlib
from typing import List, Dict, Any, Optional

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, VectorParams, PointStruct, Filter
    HAS_QDRANT = True
except ImportError:
    HAS_QDRANT = False

try:
    import openai
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

logger = logging.getLogger(__name__)

# Defaults
DEFAULT_COLLECTION = os.getenv("QDRANT_COLLECTION", "parts_catalog")
VECTOR_DIMENSION = 1536  # OpenAI text-embedding-3-small dimension
EMBEDDING_MODEL = "text-embedding-3-small"


def get_openai_embedding(text: str) -> List[float]:
    """
    Generate 1536-dimensional embedding using OpenAI text-embedding-3-small.
    Falls back to deterministic hash vector if OpenAI key is unconfigured or call fails.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key and HAS_OPENAI:
        try:
            client = openai.OpenAI(api_key=api_key)
            response = client.embeddings.create(
                input=text,
                model=EMBEDDING_MODEL
            )
            return response.data[0].embedding
        except Exception as exc:
            logger.warning("[VECTOR] OpenAI embedding call failed: %s. Using fallback vector.", exc)

    # Fallback deterministic vector generator for local testing / offline mode
    return _generate_fallback_vector(text)


def _generate_fallback_vector(text: str, dim: int = VECTOR_DIMENSION) -> List[float]:
    """Generate a deterministic normalized vector based on text hash for testing."""
    vec = []
    for i in range(dim):
        h = hashlib.sha256(f"{text}_{i}".encode('utf-8')).hexdigest()
        val = (int(h[:8], 16) / 0xFFFFFFFF) * 2.0 - 1.0
        vec.append(val)
    # Normalize vector to unit length
    norm = (sum(v * v for v in vec)) ** 0.5
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


class VectorSearchService:
    def __init__(self, host: str = None, port: int = None, collection_name: str = None):
        self.host = host or os.getenv("QDRANT_HOST", "localhost")
        self.port = port or int(os.getenv("QDRANT_PORT", "6333"))
        self.collection_name = collection_name or DEFAULT_COLLECTION
        self._client = None
        self._is_memory_fallback = False

    def get_client(self):
        if self._client is not None:
            return self._client

        if not HAS_QDRANT:
            logger.warning("[VECTOR] qdrant-client not installed. Vector search disabled.")
            return None

        try:
            self._client = QdrantClient(host=self.host, port=self.port, timeout=3.0)
            # Ping connection
            self._client.get_collections()
            logger.info("[VECTOR] Connected to Qdrant at %s:%s", self.host, self.port)
        except Exception as exc:
            logger.warning("[VECTOR] Could not connect to Qdrant at %s:%s (%s). Using in-memory fallback.", self.host, self.port, exc)
            try:
                self._client = QdrantClient(":memory:")
                self._is_memory_fallback = True
            except Exception as mem_exc:
                logger.error("[VECTOR] In-memory Qdrant initialization failed: %s", mem_exc)
                self._client = None

        if self._client is not None:
            self.ensure_collection()

        return self._client

    def ensure_collection(self) -> bool:
        client = self._client
        if not client:
            return False
        try:
            collections = [c.name for c in client.get_collections().collections]
            if self.collection_name not in collections:
                client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(size=VECTOR_DIMENSION, distance=Distance.COSINE)
                )
                logger.info("[VECTOR] Created Qdrant collection '%s'", self.collection_name)
            return True
        except Exception as exc:
            logger.error("[VECTOR] ensure_collection failed: %s", exc)
            return False

    def upsert_part(self, point_id: int, text_representation: str, payload: Dict[str, Any]) -> bool:
        client = self.get_client()
        if not client:
            return False
        try:
            vector = get_openai_embedding(text_representation)
            payload["text_representation"] = text_representation
            point = PointStruct(
                id=point_id,
                vector=vector,
                payload=payload
            )
            client.upsert(
                collection_name=self.collection_name,
                points=[point]
            )
            return True
        except Exception as exc:
            logger.error("[VECTOR] Upsert failed for point %s: %s", point_id, exc)
            return False

    def search_vector(self, query_text: str, limit: int = 5) -> List[Dict[str, Any]]:
        client = self.get_client()
        if not client:
            return []
        try:
            query_vector = get_openai_embedding(query_text)
            
            # Using query_points / search depending on client version
            search_results = []
            if hasattr(client, "search"):
                search_results = client.search(
                    collection_name=self.collection_name,
                    query_vector=query_vector,
                    limit=limit
                )
            elif hasattr(client, "query_points"):
                res = client.query_points(
                    collection_name=self.collection_name,
                    query=query_vector,
                    limit=limit
                )
                search_results = res.points

            results = []
            for hit in search_results:
                score = getattr(hit, "score", 0.0)
                payload = getattr(hit, "payload", {}) or {}
                results.append({
                    "id": getattr(hit, "id", None),
                    "score": round(float(score), 4),
                    "payload": payload,
                })
            return results
        except Exception as exc:
            logger.warning("[VECTOR] Search vector failed: %s", exc)
            return []


# Global singleton instance
_vector_service: Optional[VectorSearchService] = None

def get_vector_search_service() -> VectorSearchService:
    global _vector_service
    if _vector_service is None:
        _vector_service = VectorSearchService()
    return _vector_service
