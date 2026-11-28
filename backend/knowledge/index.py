"""Load reviewed Markdown sources and publish current versions transactionally."""

import argparse
import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, date
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import and_, delete, or_
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from backend.db import engine
from backend.knowledge.embedding import embed, normalize
from backend.knowledge.models import Chunk, Document

Department = Literal["shared", "procurement", "operations", "quality"]
DEMO_CORPUS = Path(__file__).with_name("documents")


class DocumentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,59}$")
    title: str = Field(min_length=1, max_length=120)
    version: int = Field(ge=1, le=999_999_999)
    department: Department
    role: Literal["all", "analyst", "manager"]
    updated_at: AwareDatetime
    expires_on: date | None = None


@dataclass(frozen=True)
class Paragraph:
    id: str
    section: str
    excerpt: str
    keywords: list[str]


def parse(markdown: str) -> list[Paragraph]:
    """Parse a heading, keyword list and prose paragraphs for each numbered section."""
    sections = re.split(r"^## ", markdown.replace("\r\n", "\n").strip(), flags=re.MULTILINE)
    if len(sections) < 2 or sections[0] or len(sections) > 65:
        raise ValueError("Expected 1–64 Markdown sections beginning with ##")
    paragraphs = []
    for index, section in enumerate(sections[1:], 1):
        heading, _, body = section.partition("\n")
        tags, _, prose = body.strip().partition("\n")
        keywords = list(dict.fromkeys(normalize(tag) for tag in tags.removeprefix("關鍵詞：").split("|")))
        if (
            not tags.startswith("關鍵詞：") or not 1 <= len(keywords) <= 16
            or not all(2 <= len(tag) <= 48 for tag in keywords)
            or not 1 <= len(heading.strip()) <= 160 or not prose.strip()
        ):
            raise ValueError(f"Invalid heading, keywords or body in section {index}")
        blocks = re.split(r"\n\s*\n", prose.strip())
        if len(blocks) > 32:
            raise ValueError(f"Too many paragraphs in section {index}")
        for number, block in enumerate(blocks, 1):
            excerpt = " ".join(block.split())
            if len(excerpt) > 600:
                raise ValueError(f"Split paragraphs over 600 characters in section {index}")
            paragraphs.append(Paragraph(f"{index}.{number}", heading.strip(), excerpt, keywords))
    return paragraphs


def publish(db: Session, spec: DocumentSpec, markdown: str, *, reindex: bool = False) -> bool:
    cleaned = markdown.replace("\r\n", "\n").strip()
    checksum = hashlib.sha256(f"{spec.model_dump_json()}\n{cleaned}".encode()).hexdigest()
    paragraphs = parse(cleaned)
    insert = postgres_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    values = {**spec.model_dump(), "updated_at": spec.updated_at.astimezone(UTC), "checksum": checksum}
    can_update = Document.version < spec.version
    if reindex:
        can_update = or_(can_update, and_(Document.version == spec.version, Document.checksum == checksum))
    changed = db.scalar(
        insert(Document).values(**values).on_conflict_do_update(
            index_elements=[Document.id],
            set_={key: value for key, value in values.items() if key != "id"},
            where=can_update,
        ).returning(Document.id)
    )
    if changed is None:
        current = db.get(Document, spec.id)
        if current and current.version == spec.version and current.checksum != checksum:
            raise ValueError(f"{spec.id} v{spec.version} already exists with different content; bump version")
        return False
    db.execute(delete(Chunk).where(Chunk.document_id == spec.id))
    for paragraph in paragraphs:
        searchable = " ".join((spec.title, paragraph.section, *paragraph.keywords, paragraph.excerpt))
        db.add(Chunk(document_id=spec.id, paragraph=paragraph.id, section=paragraph.section,
                     excerpt=paragraph.excerpt, keywords=paragraph.keywords, embedding=embed(searchable)))
    return True


def load_corpus(db: Session, directory: Path = DEMO_CORPUS, *, reindex: bool = False) -> int:
    changed = 0
    for path in sorted(directory.glob("*.json")):
        spec = DocumentSpec.model_validate_json(path.read_text(encoding="utf-8"))
        if path.stem != spec.id:
            raise ValueError(f"Metadata ID must match filename: {path.name}")
        markdown = path.with_suffix(".md").read_text(encoding="utf-8")
        changed += publish(db, spec, markdown, reindex=reindex)
    return changed


def main() -> None:
    command = argparse.ArgumentParser(description="Publish reviewed synthetic knowledge documents")
    command.add_argument("directory", nargs="?", type=Path, default=DEMO_CORPUS)
    command.add_argument("--reindex", action="store_true", help="Rebuild unchanged current versions")
    args = command.parse_args()
    if not args.directory.is_dir() or not any(args.directory.glob("*.json")):
        command.error("Provide a directory with document metadata JSON and matching Markdown")
    with Session(engine()) as db, db.begin():
        changed = load_corpus(db, args.directory, reindex=args.reindex)
    print(f"{changed} document(s) indexed")


if __name__ == "__main__":
    main()
