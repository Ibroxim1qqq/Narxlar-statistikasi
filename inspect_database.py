from __future__ import annotations

import sqlite3

import pandas as pd

from database import DB_PATH, database_summary


def main() -> None:
    info = database_summary()
    print("Database:", info["path"])
    if not info.get("exists"):
        print("Database file not found. Run: python daily_update.py")
        return

    print("Counts:", info.get("counts", {}))
    with sqlite3.connect(DB_PATH) as conn:
        print("\nLatest snapshots:")
        print(
            pd.read_sql_query(
                """
                SELECT snapshot_utc, projects_total, room_price_rows_total, projects_with_price
                FROM snapshots
                ORDER BY snapshot_utc DESC
                LIMIT 10
                """,
                conn,
            ).to_string(index=False)
        )

        print("\nLatest projects by source:")
        print(
            pd.read_sql_query(
                """
                SELECT source, COUNT(*) AS projects
                FROM latest_projects
                GROUP BY source
                ORDER BY projects DESC
                """,
                conn,
            ).to_string(index=False)
        )


if __name__ == "__main__":
    main()
