from uuid import UUID

from sqlalchemy import delete

from app.celery_app import celery_app
from app.db import SessionLocal
from app.models import Document, DocumentChunk, DocumentStatus
from app.services import chunk_text, embed_texts


@celery_app.task(name="ingest_document")
def ingest_document(document_id: str) -> None:
    db = SessionLocal()
    try:
        document = db.get(Document, UUID(document_id))
        if not document:
            return
        document.status = DocumentStatus.processing
        document.error_message = None
        db.commit()

        db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.id))
        chunks = chunk_text(document.content)
        embeddings = embed_texts(chunks)
        db.add_all(
            [
                DocumentChunk(
                    document_id=document.id,
                    chunk_index=index,
                    content=content,
                    embedding=embedding,
                )
                for index, (content, embedding) in enumerate(zip(chunks, embeddings, strict=True))
            ]
        )
        document.status = DocumentStatus.ready
        db.commit()
    except Exception as exc:
        db.rollback()
        document = db.get(Document, UUID(document_id))
        if document:
            document.status = DocumentStatus.failed
            document.error_message = str(exc)[:1000]
            db.commit()
        raise
    finally:
        db.close()
