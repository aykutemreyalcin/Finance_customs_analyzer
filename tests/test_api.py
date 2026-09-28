import gzip
import sqlite3

from fastapi.testclient import TestClient

from core import database


def test_api_requires_password_and_serves_box_workflow(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXA_PASSWORD", "test-password")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "nexa.db")

    # Import after the environment and DB path are isolated for this test.
    from api.index import app

    client = TestClient(app)
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/dashboard").status_code == 401

    headers = {"Authorization": "Bearer test-password"}
    assert client.get("/api/dashboard", headers=headers).status_code == 200

    created = client.post(
        "/api/boxes",
        headers=headers,
        json={"tracking_id": "TEST-001", "country": "CA", "shipment_type": "Single"},
    )
    assert created.status_code == 200

    result = client.get("/api/boxes?query=TEST-001", headers=headers)
    assert result.status_code == 200
    assert result.json()["total"] == 1

    box_id = result.json()["items"][0]["id"]
    assert client.patch(
        f"/api/boxes/{box_id}",
        headers=headers,
        json={"customer_shipping_fee": 100},
    ).status_code == 200
    assert client.get("/api/profitability", headers=headers).status_code == 200


def test_api_restores_a_gzipped_sqlite_backup_once(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXA_PASSWORD", "test-password")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    target = tmp_path / "target.db"
    source = tmp_path / "source.db"
    monkeypatch.setattr(database, "DB_PATH", target)

    source_connection = sqlite3.connect(source)
    database.init_db(source_connection)
    source_connection.execute("INSERT INTO boxes (tracking_id, country) VALUES (?, ?)", ("RESTORE-001", "CA"))
    source_connection.commit()
    source_connection.close()

    from api.index import app

    client = TestClient(app)
    response = client.post(
        "/api/admin/migrate-sqlite",
        headers={"Authorization": "Bearer test-password"},
        files={"file": ("finance_customs.db.gz", gzip.compress(source.read_bytes()), "application/gzip")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["migrated"]["boxes"] == 1
    assert client.post(
        "/api/admin/migrate-sqlite",
        headers={"Authorization": "Bearer test-password"},
        files={"file": ("finance_customs.db.gz", gzip.compress(source.read_bytes()), "application/gzip")},
    ).status_code == 409
