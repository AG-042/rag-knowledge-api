from app.celery_app import celery_app
from app.db import SessionLocal
from app.models import Chunk, Document, DocumentStatus
from app.services import chunk_text, embed_texts


@celery_app.task(name="ingest_document")
def ingest_document(document_id: int) -> None:
    db = SessionLocal()
    document = db.get(Document, document_id)
    if not document:
        db.close()
        return

    try:
        document.status = DocumentStatus.processing
        document.error_message = None
        db.commit()

        chunks = chunk_text(document.content)
        embeddings = embed_texts(chunks)

        db.query(Chunk).filter(Chunk.document_id == document.id).delete()
        for position, (content, embedding) in enumerate(zip(chunks, embeddings)):
            db.add(
                Chunk(
                    document_id=document.id,
                    position=position,
                    content=content,
                    embedding=embedding,
                )
            )

        document.status = DocumentStatus.ready
        db.commit()
    except Exception as exc:
        db.rollback()
        document = db.get(Document, document_id)
        if document:
            document.status = DocumentStatus.failed
            document.error_message = str(exc)[:1000]
            db.commit()
        raise
    finally:
        db.close()
