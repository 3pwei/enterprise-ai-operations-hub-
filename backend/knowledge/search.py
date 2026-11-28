"""Apply identity and metadata constraints before computing relevance or returning text."""

import re
from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import literal, or_, select
from sqlalchemy.orm import Session

from backend import demo
from backend.config import settings
from backend.knowledge.embedding import embed, normalize
from backend.knowledge.index import Department
from backend.knowledge.models import Chunk, Document, Lookup
from backend.models import Audit, User
from backend.security import verify_capability

TOOL = "knowledge_search"
SOURCE = "knowledge.documents"
VERSION = re.compile(r"(?<![a-z0-9])v([1-9][0-9]{0,8})(?![a-z0-9])|第\s*([1-9][0-9]{0,8})\s*版", re.IGNORECASE)
# Match permissions to both the existing synthetic identity and its current role.
DEMO_PERMISSIONS = {
    (1, "analyst"): ("shared", "operations", "quality"),
    (2, "manager"): ("shared", "procurement"),
}


class Filters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    department: Department | None = None
    document_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]{1,59}$")
    version: int | None = Field(default=None, ge=1, le=999_999_999)


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=2, max_length=1000)
    filters: Filters = Field(default_factory=Filters)

    @field_validator("message")
    @classmethod
    def trim_question(cls, message: str) -> str:
        if len(message.strip()) < 2:
            raise ValueError("Question is required")
        return message.strip()


class Citation(BaseModel):
    document_id: str
    title: str
    version: int
    department: Department
    updated_at: datetime
    section: str
    paragraph: str
    excerpt: str

    @field_validator("updated_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)

    @property
    def reference(self) -> str:
        return f"{self.document_id}@{self.version}#{self.paragraph}"


def scope(db: Session, user: User) -> tuple[tuple[str, ...], tuple[str, ...]]:
    workspace_id = demo.workspace_id(db, user)
    if settings().public_demo_mode:
        workspace = db.get(demo.DemoWorkspace, workspace_id) if workspace_id else None
        if (
            not workspace or workspace.created_at.replace(tzinfo=UTC) < datetime.now(UTC) - timedelta(seconds=demo.MAX_AGE)
            or user.role not in ("analyst", "manager")
        ):
            raise PermissionError("Active simulation session required")
        return ("shared",), ("all",)
    if workspace_id is not None or (user.id, user.role) not in DEMO_PERMISSIONS:
        raise PermissionError("Knowledge access unavailable for this identity")
    return DEMO_PERMISSIONS[user.id, user.role], ("all", user.role)


def keyword_weight(query: str, keywords: list[str]) -> float:
    lengths = [
        len(term) for term in keywords
        if re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", query)
    ]
    return min(1.0, max(lengths, default=0) / 8)


def search(db: Session, user: User, question: Question) -> tuple[list[Citation], str]:
    departments, roles = scope(db, user)
    vector = db.get_bind().dialect.name == "postgresql"
    strategy = "keyword+pgvector" if vector else "keyword+sqlite-vector"
    today = datetime.now(UTC).date()
    filters = question.filters
    versions = {int(first or second) for first, second in VERSION.findall(question.message)}
    if filters.version is not None:
        versions.add(filters.version)
    query = normalize(question.message)
    query_embedding = embed(query)
    if len(versions) > 1 or not any(query_embedding):
        return [], strategy

    eligible = select(
        Document.id.label("document_id"), Document.title, Document.version,
        Document.department, Document.updated_at, Chunk.paragraph, Chunk.section,
        Chunk.excerpt, Chunk.keywords, Chunk.embedding,
    ).join(Chunk, Chunk.document_id == Document.id).where(
        Document.department.in_(departments), Document.role.in_(roles),
        or_(Document.expires_on.is_(None), Document.expires_on > today),
    )
    if filters.department is not None:
        eligible = eligible.where(Document.department == filters.department)
    if filters.document_id is not None:
        eligible = eligible.where(Document.id == filters.document_id)
    if versions:
        eligible = eligible.where(Document.version == versions.pop())

    scoped = eligible.cte("eligible_passages")
    if vector:
        scoped = scoped.prefix_with("MATERIALIZED", dialect="postgresql")
    similarity = (
        1 - scoped.c.embedding.cosine_distance(query_embedding) if vector else literal(0.0)
    )
    statement = select(
        scoped.c.document_id, scoped.c.title, scoped.c.version, scoped.c.department,
        scoped.c.updated_at, scoped.c.paragraph, scoped.c.section, scoped.c.excerpt,
        scoped.c.keywords, similarity.label("similarity"),
    )
    if not vector:
        statement = statement.add_columns(scoped.c.embedding)

    ranked: list[tuple[float, Citation]] = []
    for row in db.execute(statement).mappings():
        weight = keyword_weight(query, row["keywords"])
        if not weight:
            continue
        cosine = row["similarity"] if vector else sum(
            left * right for left, right in zip(query_embedding, row["embedding"], strict=True)
        )
        citation = Citation.model_validate(row)
        score = 0.65 * weight + 0.35 * max(0.0, min(1.0, cosine or 0.0))
        ranked.append((score, citation))
    ranked.sort(key=lambda item: (-item[0], item[1].reference))
    return [citation for _, citation in ranked[:4]], strategy


def invoke(db: Session, capability: str, question: Question, request_id: UUID) -> dict:
    actor = 0
    outcome = "denied"
    citations: list[Citation] = []
    try:
        user = verify_capability(db, capability)
        actor = user.id
        citations, strategy = search(db, user, question)
        outcome = "matched" if citations else "no_evidence"
    except PermissionError:
        raise
    except Exception:
        outcome = "error"
        db.rollback()
        raise
    finally:
        db.add(Audit(actor_id=actor, tool=TOOL, outcome=outcome))
        db.add(Lookup(request_id=str(request_id), actor_id=actor, outcome=outcome,
                      filters=question.filters.model_dump(exclude_none=True),
                      references=[citation.reference for citation in citations]))
        db.commit()
    return {"source": SOURCE, "data": {
        "strategy": strategy, "citations": [citation.model_dump(mode="json") for citation in citations],
    }}
