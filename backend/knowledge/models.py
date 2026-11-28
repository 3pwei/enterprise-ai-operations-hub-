from datetime import UTC, date, datetime

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import JSON, Date, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.db import Base

DIMENSIONS = 384


class Document(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    version: Mapped[int]
    department: Mapped[str] = mapped_column(String(24), index=True)
    role: Mapped[str] = mapped_column(String(16))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_on: Mapped[date | None] = mapped_column(Date)
    checksum: Mapped[str] = mapped_column(String(64))


class Chunk(Base):
    __tablename__ = "knowledge_chunks"

    document_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), primary_key=True,
    )
    paragraph: Mapped[str] = mapped_column(String(16), primary_key=True)
    section: Mapped[str] = mapped_column(String(160))
    excerpt: Mapped[str] = mapped_column(Text)
    keywords: Mapped[list[str]] = mapped_column(JSON)
    embedding: Mapped[list[float]] = mapped_column(
        VECTOR(DIMENSIONS).with_variant(JSON(), "sqlite"),
    )


class Lookup(Base):
    __tablename__ = "knowledge_lookups"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36), index=True)
    actor_id: Mapped[int] = mapped_column(index=True)
    outcome: Mapped[str] = mapped_column(String(24))
    filters: Mapped[dict] = mapped_column(JSON)
    references: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
