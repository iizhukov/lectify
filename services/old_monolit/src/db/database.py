import os
import time

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from src.config import config


_engine = None
_SessionLocal = None
_testing_mode = False


def set_testing_mode(enabled: bool = True):
    """Включить тестовый режим - использовать тестовую БД"""
    global _testing_mode, _engine, _SessionLocal
    _testing_mode = enabled

    if _engine is not None:
        _engine.dispose()

    _engine = None
    _SessionLocal = None


def is_testing_mode() -> bool:
    """Проверить тестовый режим"""
    global _testing_mode
    return _testing_mode or os.environ.get("TESTING", "").lower() == "true"


def _get_database_url() -> str:
    """Получить URL базы данных"""
    if is_testing_mode():
        return config.database_test_url

    return config.database_url


def get_engine():
    """Lazy creation engine"""
    global _engine

    if _engine is None:
        url = _get_database_url()
        _engine = create_engine(
            url,
            pool_pre_ping=True,
            pool_size=config.database_pool_size,
            max_overflow=config.database_max_overflow
        )
        _register_db_metrics(_engine)

    return _engine


def _register_db_metrics(engine):
    """Регистрирует SQLAlchemy events для метрик БД"""
    from src.utils.metrics import get_metrics

    m = get_metrics()

    @event.listens_for(engine, "before_cursor_execute")
    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        conn.info.setdefault("query_start_time", []).append(time.perf_counter())

    @event.listens_for(engine, "after_cursor_execute")
    def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        start_time = conn.info["query_start_time"].pop()
        duration = time.perf_counter() - start_time

        op = _classify_operation(statement)
        m.db_operations.labels(operation=op).inc()
        m.db_operation_duration.observe(duration)


def _classify_operation(statement: str) -> str:
    stmt = statement.strip().upper()
    if stmt.startswith("SELECT"):
        return "select"
    if stmt.startswith("INSERT"):
        return "insert"
    if stmt.startswith("UPDATE"):
        return "update"
    if stmt.startswith("DELETE"):
        return "delete"
    if stmt.startswith("CREATE"):
        return "create"
    if stmt.startswith("ALTER"):
        return "alter"
    if stmt.startswith("DROP"):
        return "drop"
    return "other"


def get_session_local():
    """Lazy creation SessionLocal"""
    global _SessionLocal

    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=get_engine()
        )

    return _SessionLocal


def reset_database():
    """Сбросить подключение к БД"""
    global _engine, _SessionLocal

    if _engine is not None:
        _engine.dispose()

    _engine = None
    _SessionLocal = None


def init_sqlalchemy_db():
    """Инициализация БД - создание таблиц"""
    from src.db.entity.base import Base
    Base.metadata.create_all(bind=get_engine())


class _SessionLocalWrapper:
    """
    Обёртка для sessionmaker, позволяющая патчить SessionLocal в тестах.
    Используется как замена прямого импорта SessionLocal.
    """
    def __call__(self):
        return get_session_local()()

    def __enter__(self):
        return get_session_local()().__enter__()

    def __exit__(self, *args):
        return get_session_local()().__exit__(*args)


SessionLocal = _SessionLocalWrapper()


class _EngineProxy:
    """Прокси для engine"""
    def __getattr__(self, name):
        return getattr(get_engine(), name)

    def __call__(self, *args, **kwargs):
        return get_engine()(*args, **kwargs)


engine = _EngineProxy()
