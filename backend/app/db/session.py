from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

engine = create_engine(
    get_settings().DATABASE_URL,
    isolation_level="READ COMMITTED",
    pool_size=20,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(
    bind=engine,
    class_=Session,
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session]:
    with SessionLocal() as session:
        yield session
