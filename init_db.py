#!/usr/bin/env python3
"""
Script to initialize the database tables without starting the FastAPI backend.

Usage:
    uv run python init_db.py
"""

import sys
from urllib.parse import urlparse

from sqlalchemy import create_engine, schema, text
from sqlmodel import SQLModel

# Import all models to register them with SQLModel.metadata
from db.models import (
    Job,
    JobResult,
    User,
    Group,
    GroupUserLink,
    GroupModelLink,
    Model,
    Customer,
    NotificationsSent,
)
from utils.settings import get_settings


def create_database_if_needed(database_url: str) -> None:
    """Create the database if it doesn't exist (PostgreSQL only)."""
    parsed = urlparse(database_url)

    # Only handle PostgreSQL
    if not parsed.scheme.startswith("postgresql"):
        return

    db_name = parsed.path.lstrip("/")
    if not db_name:
        return

    # Connect to the default 'postgres' database to create the target database
    server_url = database_url.rsplit("/", 1)[0] + "/postgres"
    engine = create_engine(server_url, isolation_level="AUTOCOMMIT")

    with engine.connect() as connection:
        result = connection.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :db_name"),
            {"db_name": db_name},
        )
        if not result.fetchone():
            print(f"Creating database '{db_name}'...")
            connection.execute(text(f'CREATE DATABASE "{db_name}"'))
            print(f"Database '{db_name}' created successfully!")
        else:
            print(f"Database '{db_name}' already exists")

    engine.dispose()


def init_database():
    """Create all database tables."""
    settings = get_settings()

    print(f"Connecting to database: {settings.API_DATABASE_URL}")

    try:
        # Create the database if it doesn't exist
        create_database_if_needed(settings.API_DATABASE_URL)

        engine = create_engine(settings.API_DATABASE_URL)

        # Create schema if needed (for PostgreSQL)
        with engine.connect() as connection:
            if connection.dialect.has_schema(connection, "transcribe"):
                print("Schema 'transcribe' already exists")
            else:
                try:
                    connection.execute(schema.CreateSchema("transcribe"))
                    connection.commit()
                    print("Created schema 'transcribe'")
                except Exception as e:
                    print(f"Schema creation skipped: {e}")

        # Create all tables
        print("Creating database tables...")
        SQLModel.metadata.create_all(engine)
        print("Database tables created successfully!")

    except Exception as e:
        print(f"Failed to initialize database: {e}")
        sys.exit(1)


if __name__ == "__main__":
    init_database()
