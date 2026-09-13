import hashlib
import json

from openai import OpenAI
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Document, DocumentChunk

settings = get_settings()


def get_openai_client() -> OpenAI:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required for embedding and generation")
    return OpenAI(api_key=settings.openai_api_key)


def get_redis_client() -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


def chunk_text(text: str, size: int | None = None, overlap: int | None = None) -> list[str]:
    size = size or settings.chunk_size
    overlap = overlap or settings.chunk_overlap
    if overlap >= size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")
    clean = " ".join(text.split())
    chunks = []
    start = 0
    while start < len(clean):
        end = min(start + size, len(clean))
        chunk = clean[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(clean):
            break
        start = end - overlap
    return chunks


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    response = get_openai_client().embeddings.create(
        model=settings.openai_embedding_model,
        input=texts,
        dimensions=settings.embedding_dimensions,
    )
    return [item.embedding for item in response.data]


def search_chunks(db: Session, question: str, top_k: int) -> list[dict]:
    query_embedding = embed_texts([question])[0]
    distance = DocumentChunk.embedding.cosine_distance(query_embedding)
    stmt = (
        select(DocumentChunk, Document, distance.label("distance"))
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(Document.status == "ready")
        .order_by(distance)
        .limit(top_k)
    )
    rows = db.execute(stmt).all()
    return [
        {
            "document_id": chunk.document_id,
            "title": document.title,
            "source": document.source,
            "chunk_index": chunk.chunk_index,
            "content": chunk.content,
            "score": round(max(0.0, 1.0 - float(dist)), 4),
        }
        for chunk, document, dist in rows
    ]


def answer_question(question: str, hits: list[dict]) -> str:
    if not hits:
        return "I could not find relevant information in the knowledge base."
    context = "\n\n".join(
        f"[Source {i + 1}: {hit['title']}]\n{hit['content']}" for i, hit in enumerate(hits)
    )
    response = get_openai_client().chat.completions.create(
        model=settings.openai_chat_model,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": (
                    "Answer only from the provided context. If the context is insufficient, say so. "
                    "Cite supporting passages using [Source N]."
                ),
            },
            {"role": "user", "content": f"Question: {question}\n\nContext:\n{context}"},
        ],
    )
    return response.choices[0].message.content or "No answer generated."


def cache_key(question: str, top_k: int) -> str:
    digest = hashlib.sha256(f"{question.strip().lower()}:{top_k}".encode()).hexdigest()
    return f"rag:query:{digest}"


def get_cached(question: str, top_k: int) -> dict | None:
    raw = get_redis_client().get(cache_key(question, top_k))
    return json.loads(raw) if raw else None


def set_cached(question: str, top_k: int, payload: dict) -> None:
    get_redis_client().setex(
        cache_key(question, top_k),
        settings.query_cache_ttl,
        json.dumps(payload, default=str),
    )
