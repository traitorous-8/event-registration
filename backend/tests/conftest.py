import os
import sys
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from alembic.config import Config
from alembic import command

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/event_registration_test"
)

os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from backend.app.config import settings
settings.database_url = TEST_DATABASE_URL

from backend.app.main import app


@pytest.fixture(scope="session")
def test_engine():
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture
def clean_db(test_engine):
    """Drop and recreate public schema in test DB to ensure a clean state."""
    with test_engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
        conn.commit()


@pytest.fixture
def alembic_config():
    alembic_ini_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../alembic.ini"))
    alembic_cfg = Config(alembic_ini_path)
    alembic_cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    alembic_cfg.set_main_option("script_location", os.path.abspath(os.path.join(os.path.dirname(__file__), "../alembic")))
    return alembic_cfg


@pytest.fixture
def migrated_db(clean_db, alembic_config, test_engine):
    command.upgrade(alembic_config, "head")
    yield test_engine


@pytest.fixture
def db_session(migrated_db):
    Session = sessionmaker(bind=migrated_db)
    session = Session()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
