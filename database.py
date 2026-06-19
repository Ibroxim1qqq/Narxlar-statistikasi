from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "housing_prices.sqlite"
LOCAL_TZ = ZoneInfo("Asia/Tashkent")


def snapshot_id_from_utc(snapshot_utc: str) -> str:
    return snapshot_day_from_utc(snapshot_utc)


def snapshot_day_from_utc(snapshot_utc: str) -> str:
    normalized = snapshot_utc.replace("Z", "+00:00")
    timestamp = datetime.fromisoformat(normalized)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(LOCAL_TZ).date().isoformat()


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure_metadata_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS snapshots (
            snapshot_id TEXT PRIMARY KEY,
            snapshot_date TEXT,
            snapshot_utc TEXT NOT NULL,
            created_at_utc TEXT NOT NULL,
            projects_total INTEGER NOT NULL,
            room_price_rows_total INTEGER NOT NULL,
            projects_with_price INTEGER NOT NULL,
            projects_by_source_json TEXT,
            room_rows_by_source_json TEXT
        )
        """
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info(snapshots)").fetchall()}
    if "snapshot_date" not in columns:
        conn.execute("ALTER TABLE snapshots ADD COLUMN snapshot_date TEXT")
    rows = conn.execute(
        "SELECT snapshot_id, snapshot_utc FROM snapshots WHERE snapshot_date IS NULL OR snapshot_date = ''"
    ).fetchall()
    for snapshot_id, snapshot_utc in rows:
        conn.execute(
            "UPDATE snapshots SET snapshot_date = ? WHERE snapshot_id = ?",
            (snapshot_day_from_utc(str(snapshot_utc)), snapshot_id),
        )


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def ensure_columns(conn: sqlite3.Connection, table_name: str, frame: pd.DataFrame) -> None:
    if not table_exists(conn, table_name):
        return
    existing = {
        row[1]
        for row in conn.execute(f"PRAGMA table_info({quote_identifier(table_name)})").fetchall()
    }
    for col in frame.columns:
        if col not in existing:
            conn.execute(
                f"ALTER TABLE {quote_identifier(table_name)} ADD COLUMN {quote_identifier(col)} TEXT"
            )


def create_latest_views(conn: sqlite3.Connection) -> None:
    conn.execute("DROP VIEW IF EXISTS latest_projects")
    conn.execute("DROP VIEW IF EXISTS latest_room_prices")
    conn.execute(
        """
        CREATE VIEW latest_projects AS
        SELECT *
        FROM projects_history
        WHERE snapshot_id = (
            SELECT snapshot_id
            FROM snapshots
            ORDER BY snapshot_utc DESC
            LIMIT 1
        )
        """
    )
    conn.execute(
        """
        CREATE VIEW latest_room_prices AS
        SELECT *
        FROM room_prices_history
        WHERE snapshot_id = (
            SELECT snapshot_id
            FROM snapshots
            ORDER BY snapshot_utc DESC
            LIMIT 1
        )
        """
    )


def save_snapshot(
    projects: pd.DataFrame,
    room_prices: pd.DataFrame,
    summary: dict[str, Any],
    db_path: Path = DB_PATH,
) -> Path:
    snapshot_utc = str(summary["snapshot_utc"])
    snapshot_date = snapshot_day_from_utc(snapshot_utc)
    snapshot_id = snapshot_id_from_utc(snapshot_utc)

    projects_to_save = projects.copy()
    room_prices_to_save = room_prices.copy()
    projects_to_save.insert(0, "snapshot_id", snapshot_id)
    projects_to_save.insert(1, "snapshot_date", snapshot_date)
    room_prices_to_save.insert(0, "snapshot_id", snapshot_id)
    room_prices_to_save.insert(1, "snapshot_date", snapshot_date)

    with connect(db_path) as conn:
        ensure_metadata_tables(conn)
        existing_snapshot_ids = [
            row[0]
            for row in conn.execute(
                "SELECT snapshot_id FROM snapshots WHERE snapshot_date = ? OR snapshot_id = ?",
                (snapshot_date, snapshot_id),
            ).fetchall()
        ]
        if table_exists(conn, "projects_history"):
            for existing_id in existing_snapshot_ids:
                conn.execute("DELETE FROM projects_history WHERE snapshot_id = ?", (existing_id,))
        if table_exists(conn, "room_prices_history"):
            for existing_id in existing_snapshot_ids:
                conn.execute("DELETE FROM room_prices_history WHERE snapshot_id = ?", (existing_id,))
        conn.execute(
            "DELETE FROM snapshots WHERE snapshot_date = ? OR snapshot_id = ?",
            (snapshot_date, snapshot_id),
        )

        ensure_columns(conn, "projects_history", projects_to_save)
        ensure_columns(conn, "room_prices_history", room_prices_to_save)
        projects_to_save.to_sql("projects_history", conn, if_exists="append", index=False)
        room_prices_to_save.to_sql("room_prices_history", conn, if_exists="append", index=False)

        conn.execute(
            """
            INSERT INTO snapshots (
                snapshot_id,
                snapshot_date,
                snapshot_utc,
                created_at_utc,
                projects_total,
                room_price_rows_total,
                projects_with_price,
                projects_by_source_json,
                room_rows_by_source_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                snapshot_date,
                snapshot_utc,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                int(summary.get("projects_total", 0)),
                int(summary.get("room_price_rows_total", 0)),
                int(summary.get("projects_with_price", 0)),
                json.dumps(summary.get("projects_by_source", {}), ensure_ascii=False),
                json.dumps(summary.get("room_rows_by_source", {}), ensure_ascii=False),
            ),
        )
        create_latest_views(conn)
        conn.commit()
    return db_path


def load_latest_snapshot(db_path: Path = DB_PATH) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    if not db_path.exists():
        return pd.DataFrame(), pd.DataFrame(), {}
    with connect(db_path) as conn:
        if not table_exists(conn, "snapshots"):
            return pd.DataFrame(), pd.DataFrame(), {}
        latest = conn.execute(
            "SELECT * FROM snapshots ORDER BY snapshot_utc DESC LIMIT 1"
        ).fetchone()
        if latest is None:
            return pd.DataFrame(), pd.DataFrame(), {}
        columns = [col[0] for col in conn.execute("SELECT * FROM snapshots LIMIT 0").description]
        meta = dict(zip(columns, latest))
        projects = pd.read_sql_query("SELECT * FROM latest_projects", conn)
        room_prices = pd.read_sql_query("SELECT * FROM latest_room_prices", conn)
    return projects, room_prices, meta


def database_summary(db_path: Path = DB_PATH) -> dict[str, Any]:
    if not db_path.exists():
        return {"exists": False, "path": str(db_path)}
    with connect(db_path) as conn:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') ORDER BY name"
            ).fetchall()
        ]
        counts = {}
        for table in tables:
            counts[table] = conn.execute(f"SELECT COUNT(*) FROM {quote_identifier(table)}").fetchone()[0]
        latest = conn.execute(
            "SELECT snapshot_id, snapshot_utc, projects_total, room_price_rows_total FROM snapshots ORDER BY snapshot_utc DESC LIMIT 1"
        ).fetchone() if table_exists(conn, "snapshots") else None
    return {
        "exists": True,
        "path": str(db_path),
        "tables": tables,
        "counts": counts,
        "latest": latest,
    }
