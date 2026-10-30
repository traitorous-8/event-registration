from alembic import command
from sqlalchemy import text


def test_health_check_returns_200(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_migrations_apply_on_clean_db(clean_db, alembic_config, test_engine):
    # Apply migrations
    command.upgrade(alembic_config, "head")

    # Verify tables exist
    with test_engine.connect() as conn:
        result = conn.execute(text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
        ))
        tables = {row[0] for row in result.fetchall()}

    assert "events" in tables
    assert "registrations" in tables
    assert "notifications" in tables
    assert "alembic_version" in tables
