from fastapi import Depends, FastAPI, HTTPException, Response, status
from redis import Redis
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import get_db, init_database
from app.models import Document
from app.schemas import DocumentCreate, DocumentRead, QueryRequest, QueryResponse, SearchRequest, SearchResponse
from app.services import answer_question, retrieve
from app.tasks import ingest_document

settings = get_settings()
app = FastAPI(title="RAG Knowledge API", version="1.0.0")
redis_client = Redis.from_url(settings.redis_url)


@app.on_event("startup")
def startup() -> None:
    init_database()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready(db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
        redis_client.ping()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Dependency check failed") from exc
    return {"status": "ready"}


@app.post("/api/v1/documents", response_model=DocumentRead, status_code=status.HTTP_202_ACCEPTED)
def create_document(payload: DocumentCreate, db: Session = Depends(get_db)) -> Document:
    document = Document(title=payload.title, source=payload.source, content=payload.content)
    db.add(document)
    db.commit()
    db.refresh(document)
    ingest_document.delay(document.id)
    return document


@app.get("/api/v1/documents", response_model=list[DocumentRead])
def list_documents(db: Session = Depends(get_db)) -> list[Document]:
    return list(db.scalars(select(Document).order_by(Document.created_at.desc())).all())


@app.get("/api/v1/documents/{document_id}", response_model=DocumentRead)
def get_document(document_id: int, db: Session = Depends(get_db)) -> Document:
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@app.delete("/api/v1/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: int, db: Session = Depends(get_db)) -> Response:
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    db.delete(document)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/api/v1/search", response_model=SearchResponse)
def search(payload: SearchRequest, db: Session = Depends(get_db)) -> SearchResponse:
    return SearchResponse(results=retrieve(db, payload.question, payload.top_k))


@app.post("/api/v1/query", response_model=QueryResponse)
def query(payload: QueryRequest, db: Session = Depends(get_db)) -> QueryResponse:
    answer, sources, cached = answer_question(db, payload.question, payload.top_k)
    return QueryResponse(answer=answer, sources=sources, cached=cached)
