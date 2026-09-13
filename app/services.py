import hashlib
import json
from time import perf_counter

from openai import OpenAI
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Chunk, Document, QueryLog
from app.schemas import SourceChunk

settings = get_settings()
client = OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None
redis_client = Redis.from_url(settings.redis_url, decode_responses=True)


def chunk_text(text: str) -> list[str]:
    size = settings.chunk_size
    overlap = settings.chunk_overlap
    if overlap >= size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")

    cleaned = " ".join(text.split())
    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(len(cleaned), start + size)
        chunks.append(cleaned[start:end].strip())
        if end == len(cleaned):
            break
        start = end - overlap
    return [chunk for chunk in chunks if chunk]


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not client:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    response = client.embeddings.create(model=settings.openai_embedding_model, input=texts)
    return [item.embedding for item in response.data]


def retrieve(db: Session, question: str, top_k: int) -> list[SourceChunk]:
    query_embedding = embed_texts([question])[0]
    distance = Chunk.embedding.cosine_distance(query_embedding).label("distance")
    statement = (
        select(Chunk, Document, distance)
        .join(Document, Chunk.document_id == Document.id)
        .where(Document.status == "ready")
        .order_by(distance)
        .limit(top_k)
    )

    results: list[SourceChunk] = []
    for chunk, document, distance_value in db.execute(statement):
        results.append(
            SourceChunk(
                chunk_id=chunk.id,
                document_id=document.id,
                document_title=document.title,
                source=document.source,
                content=chunk.content,
                distance=float(distance_value),
            )
        )
    return results


def cache_key(question: str, top_k: int) -> str:
    payload = f"{question.strip().lower()}::{top_k}".encode()
    return "rag:" + hashlib.sha256(payload).hexdigest()


def get_cached_answer(question: str, top_k: int) -> dict | None:
    raw = redis_client.get(cache_key(question, top_k))
    return json.loads(raw) if raw else None


def set_cached_answer(question: str, top_k: int, payload: dict) -> None:
    redis_client.setex(cache_key(question, top_k), settings.query_cache_ttl, json.dumps(payload))


def generate_answer(question: str, sources: list[SourceChunk]) -> str:
    if not client:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    if not sources:
        return "I couldn't find enough relevant context to answer that question."

    context = "\n\n".join(
        f"[Source {index + 1}: {source.document_title}]\n{source.content}"
        for index, source in enumerate(sources)
    )
    response = client.chat.completions.create(
        model=settings.openai_chat_model,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": "Answer only from the supplied context. If the context is insufficient, say so. Refer to sources as [Source N] when useful.",
            },
            {"role": "user", "content": f"Question: {question}\n\nContext:\n{context}"},
        ],
    )
    return response.choices[0].message.content or ""


def answer_question(db: Session, question: str, top_k: int) -> tuple[str, list[SourceChunk], bool]:
    cached = get_cached_answer(question, top_k)
    if cached:
        return cached["answer"], [SourceChunk(**item) for item in cached["sources"]], True

    started = perf_counter()
    sources = retrieve(db, question, top_k)
    answer = generate_answer(question, sources)
    latency_ms = int((perf_counter() - started) * 1000)

    db.add(QueryLog(question=question, answer=answer, retrieved_count=len(sources), latency_ms=latency_ms))
    db.commit()

    payload = {"answer": answer, "sources": [source.model_dump() for source in sources]}
    set_cached_answer(question, top_k, payload)
    return answer, sources, False
