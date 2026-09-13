from fastapi import Depends, FastAPI, HTTPException, status
from redis import Redis
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import Base, engine, get_db
from app.models import Document, DocumentChunk, QueryLog
from app.schemas import DocumentCreate, DocumentRead, QueryResponse, SearchHit, SearchRequest
from app.services import answer_question, get_cached, search_chunks, set_cached
from app.tasks import ingest_document

settings = get_settings()
app = FastAPI(title="RAG Knowledge API", version="1.0.0")


@app.on_event("startup")
def startup() -> None:
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/ready")
def ready(db: Session = Depends(get_db)) -> dict:
    db.execute(text("SELECT 1"))
    Redis.from_url(settings.redis_url).ping()
    return {"status": "ready"}


@app.post("/api/v1/documents", response_model=DocumentRead, status_code=status.HTTP_202_ACCEPTED)
def create_document(payload: DocumentCreate, db: Session = Depends(get_db)) -> Document:
    document = Document(**payload.model_dump())
    db.add(document)
    db.commit()
    db.refresh(document)
    ingest_document.delay(str(document.id))
    return document


@app.get("/api/v1/documents", response_model=list[DocumentRead])
def list_documents(db: Session = Depends(get_db)) -> list[Document]:
    return list(db.scalars(select(Document).order_by(Document.created_at.desc())).all())


@app.get("/api/v1/documents/{document_id}", response_model=DocumentRead)
def get_document(document_id: str, db: Session = Depends(get_db)) -> Document:
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@app.delete("/api/v1/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: str, db: Session = Depends(get_db)) -> None:
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    db.delete(document)
    db.commit()


@app.post("/api/v1/search", response_model=list[SearchHit])
def search(payload: SearchRequest, db: Session = Depends(get_db)) -> list[dict]:
    return search_chunks(db, payload.question, payload.top_k)


@app.post("/api/v1/query", response_model=QueryResponse)
def query(payload: SearchRequest, db: Session = Depends(get_db)) -> dict:
    cached = get_cached(payload.question, payload.top_k)
    if cached:
        cached["cached"] = True
        return cached

    hits = search_chunks(db, payload.question, payload.top_k)
    answer = answer_question(payload.question, hits)
    result = {"answer": answer, "sources": hits, "cached": False}
    db.add(QueryLog(question=payload.question, answer=answer, retrieved_count=len(hits)))
    db.commit()
    set_cached(payload.question, payload.top_k, result)
    return result
