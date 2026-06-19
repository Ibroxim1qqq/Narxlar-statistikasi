from __future__ import annotations

from database import database_summary
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


if __name__ == "__main__":
    main()
