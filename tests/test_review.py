import sqlite3

from core.database import init_db
from core.review import get_invoice_review_map, set_invoice_review_status


def _map(connection):
    rows = connection.execute("SELECT invoice_no, status FROM invoice_review").fetchall()
    return dict(rows)


def test_set_invoice_review_status_upserts_by_invoice_no(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    setup_connection = sqlite3.connect(db_path)
    init_db(setup_connection)
    setup_connection.close()

    monkeypatch.setattr("core.review.get_connection", lambda: sqlite3.connect(db_path))

    set_invoice_review_status("9-1", "Approved")
    set_invoice_review_status("9-1", "Approved")

    check_connection = sqlite3.connect(db_path)
    assert check_connection.execute("SELECT COUNT(*) FROM invoice_review").fetchone()[0] == 1
    assert _map(check_connection) == {"9-1": "Approved"}
    check_connection.close()


def test_set_invoice_review_status_rejects_null_invoice_no(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    setup_connection = sqlite3.connect(db_path)
    init_db(setup_connection)
    setup_connection.close()

    monkeypatch.setattr("core.review.get_connection", lambda: sqlite3.connect(db_path))

    # Regression (found 2026-09-22): SQLite's ON CONFLICT never matches two
    # NULLs, so calling this with a NULL/NaN invoice_no used to INSERT a fresh
    # row every time instead of updating — 16,254 such rows accumulated in the
    # live DB before this guard existed.
    set_invoice_review_status(None, "Approved")
    set_invoice_review_status(float("nan"), "Approved")

    check_connection = sqlite3.connect(db_path)
    assert check_connection.execute("SELECT COUNT(*) FROM invoice_review").fetchone()[0] == 0
    check_connection.close()
