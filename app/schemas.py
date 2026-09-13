from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class DocumentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    source: str | None = Field(default=None, max_length=255)
    content: str = Field(min_length=20)


class DocumentRead(BaseModel):
    id: UUID
    title: str
    source: str | None
    status: str
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SearchRequest(BaseModel):
    question: str = Field(min_length=3)
    top_k: int = Field(default=5, ge=1, le=20)


class SearchHit(BaseModel):
    document_id: UUID
    title: str
    source: str | None
    chunk_index: int
    content: str
    score: float


class QueryResponse(BaseModel):
    answer: str
    sources: list[SearchHit]
    cached: bool = False
