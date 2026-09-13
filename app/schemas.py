from datetime import datetime

from pydantic import BaseModel, Field

from app.models import DocumentStatus


class DocumentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    source: str | None = Field(default=None, max_length=255)
    content: str = Field(min_length=20)


class DocumentRead(BaseModel):
    id: int
    title: str
    source: str | None
    status: DocumentStatus
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SearchRequest(BaseModel):
    question: str = Field(min_length=2)
    top_k: int = Field(default=5, ge=1, le=20)


class SourceChunk(BaseModel):
    chunk_id: int
    document_id: int
    document_title: str
    source: str | None
    content: str
    distance: float


class SearchResponse(BaseModel):
    results: list[SourceChunk]


class QueryRequest(SearchRequest):
    pass


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceChunk]
    cached: bool = False
