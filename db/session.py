from contextlib import contextmanager
from functools import lru_cache, wraps
from sqlalchemy import create_engine, schema
from sqlalchemy.orm import Session, sessionmaker
from sqlmodel import SQLModel
from typing import Generator
from utils.log import get_logger
from utils.settings import get_settings


log = get_logger()
settings = get_settings()


@lru_cache
def get_sessionmaker() -> sessionmaker:
    """
    Get a SQLAlchemy sessionmaker.
    Uses lru_cache to ensure only one instance is created.

    Returns:
        sessionmaker: A SQLAlchemy sessionmaker instance.
    """

    engine = create_engine(settings.API_DATABASE_URL)

    with engine.connect() as connection:
        if connection.dialect.name != "sqlite":
            if not connection.dialect.has_schema(connection, "transcribe"):
                log.info("Creating 'transcribe' schema in the database.")
                connection.execute(schema.CreateSchema("transcribe"))
                connection.commit()

    SQLModel.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """
    Provide a transactional scope around a series of operations.

    Yields:
        Session: A SQLAlchemy session.
    """

    db_session_factory = get_sessionmaker()
    session: Session = db_session_factory()

    try:
        yield session
    except Exception:
        log.error("Session rollback because of exception", exc_info=True)
        session.rollback()
        raise
    finally:
        session.commit()
        session.close()


def handle_database_errors(func) -> callable:
    """
    Decorator to handle database errors.

    Parameters:
        func (callable): The function to decorate.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        session = None
        try:
            session = get_session()
            kwargs["session"] = session

            return func(*args, **kwargs)
        except Exception as e:
            log.error(f"Database error: {e}", exc_info=True)
            raise
        finally:
            if session:
                session.close()

    return wrapper


@contextmanager
def sqla_session():
    """
    Provide a transactional scope around a series of operations.

    Yields:
        Session: A SQLAlchemy session.
    """

    session = get_session()

    try:
        yield session
        session.commit()
    except Exception as e:
        log.error(f"Session rollback because of exception: {e}", exc_info=True)
        session.rollback()
        raise
    finally:
        session.close()
