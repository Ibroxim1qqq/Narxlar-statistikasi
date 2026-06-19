from __future__ import annotations

from database import database_summary
from postgres_database import postgres_summary
from scrape_prices import main as scrape_main


def main() -> None:
    scrape_main()
    info = database_summary()
    latest = info.get("latest")
    print("Database:", info.get("path"))
    print("Tables:", ", ".join(info.get("tables", [])))
    print("Counts:", info.get("counts", {}))
    if latest:
        print("Latest snapshot:", latest)
    pg_info = postgres_summary()
    print("PostgreSQL:", pg_info.get("dsn"))
    print("PostgreSQL connected:", pg_info.get("connected", False))
    if pg_info.get("error"):
        print("PostgreSQL error:", pg_info["error"])
    elif pg_info.get("enabled"):
        print("PostgreSQL tables:", ", ".join(pg_info.get("tables", [])))
        print("PostgreSQL counts:", pg_info.get("counts", {}))


if __name__ == "__main__":
    main()
