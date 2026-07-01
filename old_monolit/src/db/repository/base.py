from contextlib import contextmanager
from typing import Generator

from src.db.database import SessionLocal


class BaseRepository:
    """Base repository with session management"""

    def __init__(self):
        self.Session = SessionLocal

    @contextmanager
    def session(self) -> Generator:
        """Context manager for database sessions"""
        from src.db.database import SessionLocal
        sess = SessionLocal()
        try:
            yield sess
            sess.commit()
        except Exception:
            sess.rollback()
            raise
        finally:
            sess.close()
