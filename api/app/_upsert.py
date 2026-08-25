"""Dialect-agnostic UPSERT helper.

SQLite and Postgres both support `INSERT ... ON CONFLICT`, but SQLAlchemy's
helpers live in different dialect modules. This wrapper picks the right one
so bandit.py / learning.py work identically on both stores.
"""
from app.config import settings

if settings.database_url.startswith("postgresql"):
    from sqlalchemy.dialects.postgresql import insert as _insert
else:
    from sqlalchemy.dialects.sqlite import insert as _insert

insert = _insert
