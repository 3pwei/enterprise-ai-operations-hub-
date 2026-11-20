from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.config import settings


class Base(DeclarativeBase):
    pass


@lru_cache
def engine():
    instance = create_engine(settings().database_url, pool_pre_ping=True)
    if instance.dialect.name == "sqlite":
        @event.listens_for(instance, "connect")
        def enforce_foreign_keys(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")
    return instance


def session() -> Iterator[Session]:
    with sessionmaker(engine())() as db:
        yield db
