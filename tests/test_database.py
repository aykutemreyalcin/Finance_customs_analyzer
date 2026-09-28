import sqlite3

import numpy as np

from core.database import init_db, update_box_fields


def test_update_box_fields_accepts_numpy_int64_id(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    setup_connection = sqlite3.connect(db_path)
    init_db(setup_connection)
    setup_connection.execute("INSERT INTO boxes (id, tracking_id, country) VALUES (5835, '123', NULL)")
    setup_connection.commit()
    setup_connection.close()

    monkeypatch.setattr("core.database.get_connection", lambda: sqlite3.connect(db_path))
    # A row id read out of a pandas DataFrame (e.g. selected_issue["id"] on the
    # Data Quality page) comes back as numpy.int64, not a plain int. Regression
    # for a real bug (found 2026-09-22, fixing M-5): sqlite3 silently matches
    # zero rows for a numpy.int64 bind instead of raising, so the Data Quality
    # "Edit box" form had never actually saved anything.
    update_box_fields(np.int64(5835), {"country": "DE"})

    verify_connection = sqlite3.connect(db_path)
    assert verify_connection.execute("SELECT country FROM boxes WHERE id = 5835").fetchone() == ("DE",)
    verify_connection.close()
