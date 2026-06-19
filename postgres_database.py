from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from database import ROOT, quote_identifier, snapshot_day_from_utc, snapshot_id_from_utc


ENV_PATH = ROOT / ".env"
DEFAULT_POSTGRES_URL = "postgresql+psycopg://narxlar_app:narxlar2026@localhost:5432/narxlar_statistikasi"
POSTGRES_TABLES = {
    "snapshots",
    "projects_history",
    "room_prices_history",
    "latest_projects",
    "latest_room_prices",
}


def load_local_env() -> None:
    if not ENV_PATH.exists():
        return
    for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def postgres_dsn() -> str | None:
    load_local_env()
    return os.getenv("POSTGRES_DSN") or os.getenv("DATABASE_URL")


def postgres_enabled() -> bool:
    return bool(postgres_dsn())


def normalize_dsn(dsn: str) -> str:
    if dsn.startswith("postgres://"):
        dsn = "postgresql://" + dsn.removeprefix("postgres://")
    if dsn.startswith("postgresql://"):
        dsn = "postgresql+psycopg://" + dsn.removeprefix("postgresql://")
    return dsn


def redact_dsn(dsn: str | None = None) -> str:
    if not dsn:
        dsn = postgres_dsn()
    if not dsn:
        return "POSTGRES_DSN sozlanmagan"
    try:
        from sqlalchemy.engine import make_url

        url = make_url(normalize_dsn(dsn))
        return url.set(password="***").render_as_string(hide_password=False)
    except Exception:
        return dsn.split("@", 1)[-1] if "@" in dsn else dsn


def get_engine(dsn: str | None = None):
    dsn = dsn or postgres_dsn()
    if not dsn:
        raise RuntimeError("POSTGRES_DSN yoki DATABASE_URL sozlanmagan.")
    try:
        from sqlalchemy import create_engine
    except ImportError as exc:
        raise RuntimeError("PostgreSQL uchun `sqlalchemy` va `psycopg[binary]` paketlari kerak.") from exc
    return create_engine(normalize_dsn(dsn), pool_pre_ping=True)


def pg_text(sql: str):
    from sqlalchemy import text

    return text(sql)


def relation_exists(conn, relation_name: str) -> bool:
    row = conn.execute(
        pg_text(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = :name
            UNION ALL
            SELECT 1
            FROM information_schema.views
            WHERE table_schema = 'public' AND table_name = :name
            LIMIT 1
            """
        ),
        {"name": relation_name},
    ).fetchone()
    return row is not None


def ensure_snapshots_table(conn) -> None:
    conn.execute(
        pg_text(
            """
            CREATE TABLE IF NOT EXISTS snapshots (
                snapshot_id TEXT PRIMARY KEY,
                snapshot_date TEXT,
                snapshot_utc TEXT NOT NULL,
                created_at_utc TEXT NOT NULL,
                projects_total BIGINT NOT NULL,
                room_price_rows_total BIGINT NOT NULL,
                projects_with_price BIGINT NOT NULL,
                projects_by_source_json TEXT,
                room_rows_by_source_json TEXT
            )
            """
        )
    )
    existing = column_names(conn, "snapshots")
    if "snapshot_date" not in existing:
        conn.execute(pg_text('ALTER TABLE "snapshots" ADD COLUMN "snapshot_date" TEXT'))
    rows = conn.execute(
        pg_text(
            """
            SELECT snapshot_id, snapshot_utc
            FROM snapshots
            WHERE snapshot_date IS NULL OR snapshot_date = ''
            """
        )
    ).fetchall()
    for snapshot_id, snapshot_utc in rows:
        conn.execute(
            pg_text("UPDATE snapshots SET snapshot_date = :snapshot_date WHERE snapshot_id = :snapshot_id"),
            {
                "snapshot_date": snapshot_day_from_utc(str(snapshot_utc)),
                "snapshot_id": snapshot_id,
            },
        )


def column_names(conn, table_name: str) -> set[str]:
    rows = conn.execute(
        pg_text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = :table_name
            """
        ),
        {"table_name": table_name},
    ).fetchall()
    return {row[0] for row in rows}


def postgres_column_type(series: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(series):
        return "BOOLEAN"
    if pd.api.types.is_integer_dtype(series):
        return "BIGINT"
    if pd.api.types.is_float_dtype(series):
        return "DOUBLE PRECISION"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "TIMESTAMPTZ"
    return "TEXT"


def ensure_frame_columns(conn, table_name: str, frame: pd.DataFrame) -> None:
    if not relation_exists(conn, table_name):
        return
    existing = column_names(conn, table_name)
    for col in frame.columns:
        if col not in existing:
            conn.execute(
                pg_text(
                    f"ALTER TABLE {quote_identifier(table_name)} "
                    f"ADD COLUMN {quote_identifier(col)} {postgres_column_type(frame[col])}"
                )
            )


def create_latest_views(conn) -> None:
    conn.execute(pg_text("DROP VIEW IF EXISTS latest_projects"))
    conn.execute(pg_text("DROP VIEW IF EXISTS latest_room_prices"))
    conn.execute(
        pg_text(
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
    )
    conn.execute(
        pg_text(
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
    )


def prepare_snapshot_frames(
    projects: pd.DataFrame,
    room_prices: pd.DataFrame,
    summary: dict[str, Any],
) -> tuple[str, str, pd.DataFrame, pd.DataFrame]:
    snapshot_utc = str(summary["snapshot_utc"])
    snapshot_date = snapshot_day_from_utc(snapshot_utc)
    snapshot_id = snapshot_id_from_utc(snapshot_utc)

    projects_to_save = projects.copy()
    room_prices_to_save = room_prices.copy()
    projects_to_save.insert(0, "snapshot_id", snapshot_id)
    projects_to_save.insert(1, "snapshot_date", snapshot_date)
    room_prices_to_save.insert(0, "snapshot_id", snapshot_id)
    room_prices_to_save.insert(1, "snapshot_date", snapshot_date)
    return snapshot_id, snapshot_date, projects_to_save, room_prices_to_save


def save_snapshot_postgres(
    projects: pd.DataFrame,
    room_prices: pd.DataFrame,
    summary: dict[str, Any],
    dsn: str | None = None,
) -> dict[str, Any]:
    if not (dsn or postgres_enabled()):
        return {"enabled": False}

    snapshot_id, snapshot_date, projects_to_save, room_prices_to_save = prepare_snapshot_frames(
        projects,
        room_prices,
        summary,
    )
    snapshot_utc = str(summary["snapshot_utc"])

    engine = get_engine(dsn)
    with engine.begin() as conn:
        ensure_snapshots_table(conn)
        ensure_frame_columns(conn, "projects_history", projects_to_save)
        ensure_frame_columns(conn, "room_prices_history", room_prices_to_save)

        existing_snapshot_ids = [
            row[0]
            for row in conn.execute(
                pg_text(
                    """
                    SELECT snapshot_id
                    FROM snapshots
                    WHERE snapshot_date = :snapshot_date OR snapshot_id = :snapshot_id
                    """
                ),
                {"snapshot_date": snapshot_date, "snapshot_id": snapshot_id},
            ).fetchall()
        ]
        for existing_id in existing_snapshot_ids:
            if relation_exists(conn, "projects_history"):
                conn.execute(
                    pg_text("DELETE FROM projects_history WHERE snapshot_id = :snapshot_id"),
                    {"snapshot_id": existing_id},
                )
            if relation_exists(conn, "room_prices_history"):
                conn.execute(
                    pg_text("DELETE FROM room_prices_history WHERE snapshot_id = :snapshot_id"),
                    {"snapshot_id": existing_id},
                )
        conn.execute(
            pg_text("DELETE FROM snapshots WHERE snapshot_date = :snapshot_date OR snapshot_id = :snapshot_id"),
            {"snapshot_date": snapshot_date, "snapshot_id": snapshot_id},
        )

        projects_to_save.to_sql("projects_history", conn, if_exists="append", index=False, method="multi")
        room_prices_to_save.to_sql("room_prices_history", conn, if_exists="append", index=False, method="multi")
        conn.execute(
            pg_text(
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
                VALUES (
                    :snapshot_id,
                    :snapshot_date,
                    :snapshot_utc,
                    :created_at_utc,
                    :projects_total,
                    :room_price_rows_total,
                    :projects_with_price,
                    :projects_by_source_json,
                    :room_rows_by_source_json
                )
                """
            ),
            {
                "snapshot_id": snapshot_id,
                "snapshot_date": snapshot_date,
                "snapshot_utc": snapshot_utc,
                "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "projects_total": int(summary.get("projects_total", 0)),
                "room_price_rows_total": int(summary.get("room_price_rows_total", 0)),
                "projects_with_price": int(summary.get("projects_with_price", 0)),
                "projects_by_source_json": json.dumps(summary.get("projects_by_source", {}), ensure_ascii=False),
                "room_rows_by_source_json": json.dumps(summary.get("room_rows_by_source", {}), ensure_ascii=False),
            },
        )
        create_latest_views(conn)

    return {
        "enabled": True,
        "dsn": redact_dsn(dsn),
        "snapshot_id": snapshot_id,
        "snapshot_date": snapshot_date,
        "projects": len(projects_to_save),
        "room_rows": len(room_prices_to_save),
    }


def load_latest_snapshot_postgres(
    dsn: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    if not (dsn or postgres_enabled()):
        return pd.DataFrame(), pd.DataFrame(), {"enabled": False}

    engine = get_engine(dsn)
    with engine.begin() as conn:
        if not relation_exists(conn, "snapshots"):
            return pd.DataFrame(), pd.DataFrame(), {"enabled": True, "empty": True}
        if not relation_exists(conn, "latest_projects") or not relation_exists(conn, "latest_room_prices"):
            create_latest_views(conn)
        latest = conn.execute(
            pg_text("SELECT * FROM snapshots ORDER BY snapshot_utc DESC LIMIT 1")
        ).mappings().first()
        if latest is None:
            return pd.DataFrame(), pd.DataFrame(), {"enabled": True, "empty": True}
        projects = pd.read_sql_query(pg_text("SELECT * FROM latest_projects"), conn)
        room_prices = pd.read_sql_query(pg_text("SELECT * FROM latest_room_prices"), conn)
    meta = dict(latest)
    meta["storage"] = "postgresql"
    meta["dsn"] = redact_dsn(dsn)
    return projects, room_prices, meta


def postgres_summary(dsn: str | None = None) -> dict[str, Any]:
    if not (dsn or postgres_enabled()):
        return {"enabled": False, "dsn": redact_dsn(dsn)}
    try:
        engine = get_engine(dsn)
        with engine.begin() as conn:
            tables = [
                row[0]
                for row in conn.execute(
                    pg_text(
                        """
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = 'public'
                        UNION
                        SELECT table_name
                        FROM information_schema.views
                        WHERE table_schema = 'public'
                        ORDER BY table_name
                        """
                    )
                ).fetchall()
            ]
            counts = {}
            for table in tables:
                if table in POSTGRES_TABLES:
                    counts[table] = conn.execute(
                        pg_text(f"SELECT COUNT(*) FROM {quote_identifier(table)}")
                    ).fetchone()[0]
            latest = None
            if "snapshots" in tables:
                latest = conn.execute(
                    pg_text(
                        """
                        SELECT snapshot_id, snapshot_utc, projects_total, room_price_rows_total
                        FROM snapshots
                        ORDER BY snapshot_utc DESC
                        LIMIT 1
                        """
                    )
                ).fetchone()
    except Exception as exc:
        return {"enabled": True, "connected": False, "dsn": redact_dsn(dsn), "error": str(exc)}
    return {
        "enabled": True,
        "connected": True,
        "dsn": redact_dsn(dsn),
        "tables": tables,
        "counts": counts,
        "latest": latest,
    }


def postgres_table_preview(table_name: str, limit: int = 300, dsn: str | None = None) -> pd.DataFrame:
    if table_name not in POSTGRES_TABLES:
        raise ValueError(f"Unsupported PostgreSQL table/view: {table_name}")
    engine = get_engine(dsn)
    with engine.begin() as conn:
        return pd.read_sql_query(
            pg_text(f"SELECT * FROM {quote_identifier(table_name)} LIMIT :limit"),
            conn,
            params={"limit": int(limit)},
        )
