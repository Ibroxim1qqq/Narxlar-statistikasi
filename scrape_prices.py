from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

from database import save_snapshot
from postgres_database import save_snapshot_postgres


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
    ),
    "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "uz,en;q=0.8,ru;q=0.7",
}


@dataclass
class ScrapeResult:
    projects: list[dict[str, Any]]
    room_prices: list[dict[str, Any]]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value).replace("\xa0", " ")).strip()
    return text or None


def to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isnan(value) if isinstance(value, float) else False:
            return None
        return float(value)
    text = str(value).replace("\xa0", " ").replace(",", ".").strip()
    text = re.sub(r"(?i)[^0-9e.+-]", "", text)
    if not text or text in {"-", "."}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def to_int(value: Any) -> int | None:
    num = to_float(value)
    return int(round(num)) if num is not None else None


def normal_room_count(value: Any) -> int | None:
    rooms = to_int(value)
    if rooms is None or rooms < 0 or rooms > 8:
        return None
    return rooms


def get_nested(data: dict[str, Any] | None, path: str, default: Any = None) -> Any:
    cur: Any = data
    for key in path.split("."):
        if cur is None:
            return default
        if isinstance(cur, dict):
            cur = cur.get(key)
        else:
            return default
    return default if cur is None else cur


def save_raw(name: str, data: Any) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / name
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def request_json(url: str, *, referer: str | None = None, params: dict[str, Any] | None = None) -> dict[str, Any]:
    headers = dict(HEADERS)
    if referer:
        headers["Referer"] = referer
    response = requests.get(url, headers=headers, params=params, timeout=45)
    response.raise_for_status()
    return response.json()


def request_text(url: str, *, referer: str | None = None) -> str:
    headers = dict(HEADERS)
    if referer:
        headers["Referer"] = referer
    response = requests.get(url, headers=headers, timeout=45)
    response.raise_for_status()
    return response.text


def project_base(source: str, source_url: str, source_id: Any, name: Any) -> dict[str, Any]:
    return {
        "snapshot_utc": SNAPSHOT_UTC,
        "source": source,
        "source_url": source_url,
        "source_id": str(source_id) if source_id is not None else None,
        "project_name": clean_text(name),
        "developer": None,
        "city": None,
        "district": None,
        "address": None,
        "class": None,
        "completion": None,
        "latitude": None,
        "longitude": None,
        "price_available": False,
        "price_note": None,
        "price_total_min_uzs": None,
        "price_total_max_uzs": None,
        "price_total_min_usd": None,
        "price_total_max_usd": None,
        "price_per_sqm_min_uzs": None,
        "price_per_sqm_min_usd": None,
        "min_area_sqm": None,
        "max_area_sqm": None,
        "rooms_available": None,
        "payment_methods": None,
    }


def room_base(source: str, source_url: str, source_id: Any, project_name: Any) -> dict[str, Any]:
    return {
        "snapshot_utc": SNAPSHOT_UTC,
        "source": source,
        "source_url": source_url,
        "source_id": str(source_id) if source_id is not None else None,
        "project_name": clean_text(project_name),
        "developer": None,
        "city": None,
        "district": None,
        "rooms": None,
        "min_area_sqm": None,
        "min_total_price_uzs": None,
        "min_total_price_usd": None,
        "price_per_sqm_uzs": None,
        "price_per_sqm_usd": None,
        "price_basis": None,
    }


def add_room_from_project(
    rows: list[dict[str, Any]],
    project: dict[str, Any],
    rooms: Any,
    area: Any,
    *,
    total_uzs: Any = None,
    total_usd: Any = None,
    sqm_uzs: Any = None,
    sqm_usd: Any = None,
    basis: str,
) -> None:
    rooms_i = normal_room_count(rooms)
    if rooms_i is None:
        return
    area_f = to_float(area)
    total_uzs_i = to_int(total_uzs)
    total_usd_i = to_int(total_usd)
    sqm_uzs_i = to_int(sqm_uzs)
    sqm_usd_i = to_int(sqm_usd)
    if sqm_uzs_i is None and total_uzs_i and area_f:
        sqm_uzs_i = int(round(total_uzs_i / area_f))
    if sqm_usd_i is None and total_usd_i and area_f:
        sqm_usd_i = int(round(total_usd_i / area_f))
    if total_uzs_i is None and sqm_uzs_i and area_f:
        total_uzs_i = int(round(sqm_uzs_i * area_f))
        if "estimated" not in basis:
            basis = f"{basis}; estimated_total_from_sqm"
    if total_usd_i is None and sqm_usd_i and area_f:
        total_usd_i = int(round(sqm_usd_i * area_f))
        if "estimated" not in basis:
            basis = f"{basis}; estimated_total_from_sqm"

    row = room_base(project["source"], project["source_url"], project["source_id"], project["project_name"])
    row.update(
        {
            "developer": project.get("developer"),
            "city": project.get("city"),
            "district": project.get("district"),
            "rooms": rooms_i,
            "min_area_sqm": area_f,
            "min_total_price_uzs": total_uzs_i,
            "min_total_price_usd": total_usd_i,
            "price_per_sqm_uzs": sqm_uzs_i,
            "price_per_sqm_usd": sqm_usd_i,
            "price_basis": basis,
        }
    )
    rows.append(row)


def fetch_uysot() -> ScrapeResult:
    source = "uysot"
    source_url = "https://uysot.uz/uz/uzbekistan/novostroyki"
    api_url = "https://marketplace.uysot.uz/main/complex/view"
    projects: list[dict[str, Any]] = []
    rooms: list[dict[str, Any]] = []
    raw_pages = []

    page = 1
    size = 50
    while True:
        payload = request_json(
            api_url,
            referer=source_url,
            params={"page": page, "size": size},
        )
        data = payload["data"]
        raw_pages.append(data)
        for item in data.get("data", []):
            district = get_nested(item, "district.name.uz")
            city = get_nested(item, "district.city.name.uz")
            project = project_base(source, source_url, item.get("id"), item.get("name"))
            stats = item.get("apartment_statistics") or []
            min_area = min([to_float(x.get("min_area")) for x in stats if to_float(x.get("min_area"))], default=None)
            max_area = max([to_float(x.get("min_area")) for x in stats if to_float(x.get("min_area"))], default=None)
            room_labels = sorted({normal_room_count(x.get("rooms_count")) for x in stats if normal_room_count(x.get("rooms_count")) is not None})
            project.update(
                {
                    "developer": get_nested(item, "builder.name") or get_nested(item, "company.brand_name"),
                    "city": city,
                    "district": district,
                    "address": clean_text(get_nested(item, "nearest_place.name.uz")),
                    "class": get_nested(item, "class.name.uz"),
                    "latitude": to_float(item.get("latitude")),
                    "longitude": to_float(item.get("longitude")),
                    "price_available": bool(item.get("price_permission") and item.get("min_total_price")),
                    "price_note": None if item.get("price_permission") else "price permission false",
                    "price_total_min_uzs": to_int(item.get("min_total_price")),
                    "price_total_max_uzs": to_int(item.get("max_total_price")),
                    "min_area_sqm": min_area,
                    "max_area_sqm": max_area,
                    "rooms_available": ", ".join(str(x) for x in room_labels) if room_labels else None,
                    "payment_methods": ", ".join(
                        clean_text(get_nested(method, "name.uz")) or ""
                        for method in item.get("payment_methods", [])
                    )
                    or None,
                }
            )
            projects.append(project)

            for stat in stats:
                add_room_from_project(
                    rooms,
                    project,
                    stat.get("rooms_count"),
                    stat.get("min_area"),
                    total_uzs=stat.get("min_total_price"),
                    basis="listed_min_total",
                )

        if page * size >= data.get("total", 0):
            break
        page += 1
        time.sleep(0.25)

    save_raw("uysot_complex_pages.json", raw_pages)
    return ScrapeResult(projects, rooms)


def fetch_salomuy() -> ScrapeResult:
    source = "salomuy"
    source_url = "https://salomuy.uz/"
    api_url = "https://api.salomuy.uz/search/api/v2/complexes"
    projects: list[dict[str, Any]] = []
    rooms: list[dict[str, Any]] = []
    raw_pages = []

    limit = 100
    offset = 0
    while True:
        payload = request_json(
            api_url,
            referer=source_url,
            params={
                "limit": limit,
                "offset": offset,
                "statuses": ["published", "sold"],
                "ccy": "USD",
            },
        )
        raw_pages.append(payload)
        for item in payload.get("result", []):
            info = item.get("info") or {}
            address = get_nested(item, "object.address.display_address") or get_nested(item, "object.address.address")
            city, district = split_salomuy_address(address)
            price = info.get("price") or {}
            ppm = info.get("price_per_meter") or {}
            layouts = item.get("layouts") or []
            min_area = min([to_float(x.get("area_min")) for x in layouts if to_float(x.get("area_min"))], default=None)
            max_area = max([to_float(x.get("area_min")) for x in layouts if to_float(x.get("area_min"))], default=None)
            room_labels = sorted({normal_room_count(x.get("room")) for x in layouts if normal_room_count(x.get("room")) is not None})
            completion = get_nested(info, "completion_info.date.start")
            completion_end = get_nested(info, "completion_info.date.end")
            if completion_end and completion_end != completion:
                completion = f"{completion} - {completion_end}" if completion else completion_end
            project = project_base(source, source_url, item.get("id"), info.get("name"))
            project.update(
                {
                    "developer": get_nested(item, "developer.name"),
                    "city": city,
                    "district": district,
                    "address": clean_text(address),
                    "completion": clean_text(completion),
                    "price_available": bool(to_float(get_nested(price, "UZS.min")) or to_float(get_nested(ppm, "UZS.min"))),
                    "price_note": None if (to_float(get_nested(price, "UZS.min")) or to_float(get_nested(ppm, "UZS.min"))) else "price on request",
                    "price_total_min_uzs": to_int(get_nested(price, "UZS.min")),
                    "price_total_max_uzs": to_int(get_nested(price, "UZS.max")),
                    "price_total_min_usd": to_int(get_nested(price, "USD.min")),
                    "price_total_max_usd": to_int(get_nested(price, "USD.max")),
                    "price_per_sqm_min_uzs": to_int(get_nested(ppm, "UZS.min")),
                    "price_per_sqm_min_usd": to_int(get_nested(ppm, "USD.min")),
                    "min_area_sqm": min_area,
                    "max_area_sqm": max_area,
                    "rooms_available": ", ".join(str(x) for x in room_labels) if room_labels else None,
                    "payment_methods": ", ".join(
                        clean_text(tag.get("name")) or ""
                        for tag in info.get("tags", [])
                    )
                    or None,
                }
            )
            projects.append(project)

            for layout in layouts:
                add_room_from_project(
                    rooms,
                    project,
                    layout.get("room"),
                    layout.get("area_min"),
                    total_uzs=get_nested(price, "UZS.min"),
                    total_usd=get_nested(price, "USD.min"),
                    sqm_uzs=get_nested(ppm, "UZS.min"),
                    sqm_usd=get_nested(ppm, "USD.min"),
                    basis="project_min_or_estimated_from_sqm",
                )

        meta = payload.get("pagination") or {}
        offset += limit
        if offset >= meta.get("total", 0):
            break
        time.sleep(0.25)

    save_raw("salomuy_complex_pages.json", raw_pages)
    return ScrapeResult(projects, rooms)


def split_salomuy_address(address: str | None) -> tuple[str | None, str | None]:
    text = clean_text(address)
    if not text:
        return None, None
    parts = [clean_text(part) for part in text.split(",")]
    parts = [part for part in parts if part]
    city = parts[0] if parts else None
    district = parts[1] if len(parts) > 1 else None
    replacements = {
        "город Ташкент": "Toshkent shahri",
        "Ташкентская область": "Toshkent viloyati",
    }
    city = replacements.get(city, city)
    return city, district


def fetch_yangiuylar() -> ScrapeResult:
    source = "yangiuylar"
    source_url = "https://yangiuylar.uz/objects/building"
    api_url = "https://yangiuylar.uz/api/object/filter"
    projects: list[dict[str, Any]] = []
    rooms: list[dict[str, Any]] = []

    regions = request_json("https://yangiuylar.uz/api/region", referer=source_url, params={"limit": 100}).get("data", [])
    districts = request_json("https://yangiuylar.uz/api/district", referer=source_url, params={"limit": 1000}).get("data", [])
    region_by_id = {x.get("id"): x for x in regions}
    district_by_id = {x.get("id"): x for x in districts}

    raw_pages = []
    page = 1
    limit = 100
    while True:
        payload = request_json(
            api_url,
            referer=source_url,
            params={
                "include": "file,optionItems.parent,metro.place,company,cashback",
                "limit": limit,
                "page": page,
                "filter[type]": 1,
            },
        )
        raw_pages.append(payload)
        for item in payload.get("data", []):
            region = region_by_id.get(item.get("region_id")) or {}
            district = district_by_id.get(item.get("district_id")) or {}
            plannings = item.get("plannings") or []
            min_area = min([to_float(x.get("total_space")) for x in plannings if to_float(x.get("total_space"))], default=None)
            max_area = max([to_float(x.get("total_space")) for x in plannings if to_float(x.get("total_space"))], default=None)
            room_labels = sorted({normal_room_count(x.get("rooms")) for x in plannings if normal_room_count(x.get("rooms")) is not None})
            project_url = urljoin("https://yangiuylar.uz", f"/novostroyka/{item.get('slug')}")
            project = project_base(source, project_url, item.get("id"), item.get("name"))
            project.update(
                {
                    "developer": get_nested(item, "company.name"),
                    "city": clean_text(region.get("name_uz") or region.get("name_ru")),
                    "district": clean_text(district.get("name_uz") or district.get("name_ru")),
                    "address": clean_text(item.get("address")),
                    "completion": clean_text(item.get("completion_year") or item.get("completion_date")),
                    "latitude": to_float(item.get("latitude")),
                    "longitude": to_float(item.get("longitude")),
                    "price_available": bool(to_float(item.get("price"))),
                    "price_note": None if to_float(item.get("price")) else "price on request",
                    "price_per_sqm_min_uzs": to_int(item.get("price")),
                    "min_area_sqm": min_area,
                    "max_area_sqm": max_area,
                    "rooms_available": ", ".join(str(x) for x in room_labels) if room_labels else None,
                    "payment_methods": f"Muddatli to'lov {item.get('installment')} oy" if item.get("installment") else None,
                }
            )
            projects.append(project)

            for room_num, group in min_area_by_room(plannings, "rooms", "total_space").items():
                add_room_from_project(
                    rooms,
                    project,
                    room_num,
                    group,
                    sqm_uzs=item.get("price"),
                    basis="estimated_total_from_sqm",
                )

        meta = payload.get("meta") or {}
        if page >= meta.get("lastPage", 1):
            break
        page += 1
        time.sleep(0.25)

    save_raw("yangiuylar_object_pages.json", raw_pages)
    save_raw("yangiuylar_regions.json", regions)
    save_raw("yangiuylar_districts.json", districts)
    return ScrapeResult(projects, rooms)


def min_area_by_room(rows: list[dict[str, Any]], room_key: str, area_key: str) -> dict[int, float]:
    result: dict[int, float] = {}
    for row in rows:
        room = normal_room_count(row.get(room_key))
        area = to_float(row.get(area_key))
        if room is None or area is None:
            continue
        result[room] = min(result.get(room, area), area)
    return result


DOMTUT_DISTRICTS = [
    "olmazor",
    "bektemir",
    "chilonzor",
    "mirobod",
    "mirzo-ulugbek",
    "yakkasaroy",
    "yashnobod",
    "yunusobod",
    "yangixayot",
    "sergeli",
    "shayxontohur",
    "uchtepa",
    "parkent",
    "kibray",
    "zangiota",
]


def fetch_domtut() -> ScrapeResult:
    source = "domtut"
    projects: list[dict[str, Any]] = []
    rooms: list[dict[str, Any]] = []
    seen: set[str] = set()
    raw_pages: dict[str, str] = {}

    urls = ["https://domtut.uz/uz/catalog-nedvijimosty"] + [
        f"https://domtut.uz/uz/catalog-nedvijimosty/{district}" for district in DOMTUT_DISTRICTS
    ]
    for url in urls:
        try:
            html = request_text(url)
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                print(f"Skipping domtut 404 page: {url}")
                continue
            raise
        raw_pages[url] = html
        soup = BeautifulSoup(html, "lxml")
        for card in soup.select("article.property-card"):
            slug = card.get("data-slug")
            if not slug or slug in seen:
                continue
            seen.add(slug)
            text = clean_text(card.get_text(" ", strip=True)) or ""
            name_el = card.select_one(".h5") or card.select_one('[itemprop="name"]')
            name = None
            if name_el:
                name = name_el.get("content") if name_el.name == "meta" else name_el.get_text(" ", strip=True)
            if not name:
                m = re.search(r"TJ\s+«([^»]+)»", text)
                name = m.group(1) if m else slug
            developer = None
            brand = card.select_one('[itemprop="brand"] meta[itemprop="name"]')
            if brand:
                developer = brand.get("content")
            if not developer:
                meta_name = card.select_one('meta[itemprop="name"]')
                developer = meta_name.get("content") if meta_name else None
            district = extract_domtut_district(text)
            project_url = urljoin("https://domtut.uz", f"/uz/nedvizhimost/{slug}")
            project = project_base(source, project_url, slug, name)
            project.update(
                {
                    "developer": clean_text(developer),
                    "city": "Toshkent shahri" if district and district not in {"Kibray", "Zangiota", "Parkent"} else "Toshkent viloyati",
                    "district": district,
                    "address": extract_domtut_address(text),
                    "class": extract_domtut_class(card),
                    "completion": extract_domtut_completion(text),
                    "price_available": "Kelishilgan" not in text and bool(re.search(r"\d", text)),
                    "price_note": "negotiable" if "Kelishilgan" in text else None,
                }
            )
            room_entries = extract_domtut_room_prices(text)
            if room_entries:
                areas = [entry["area"] for entry in room_entries if entry["area"]]
                project["min_area_sqm"] = min(areas) if areas else None
                project["max_area_sqm"] = max(areas) if areas else None
                project["rooms_available"] = ", ".join(str(entry["rooms"]) for entry in room_entries if entry["rooms"])
                totals = [entry["total_uzs"] for entry in room_entries if entry["total_uzs"]]
                if totals:
                    project["price_total_min_uzs"] = min(totals)
                    project["price_total_max_uzs"] = max(totals)
                sqms = [
                    int(round(entry["total_uzs"] / entry["area"]))
                    for entry in room_entries
                    if entry["total_uzs"] and entry["area"]
                ]
                if sqms:
                    project["price_per_sqm_min_uzs"] = min(sqms)
                project["price_available"] = bool(totals)
            projects.append(project)
            for entry in room_entries:
                add_room_from_project(
                    rooms,
                    project,
                    entry["rooms"],
                    entry["area"],
                    total_uzs=entry["total_uzs"],
                    basis="listed_min_total",
                )
        time.sleep(0.2)

    save_raw("domtut_pages_index.json", {"urls": list(raw_pages.keys()), "fetched": len(raw_pages)})
    return ScrapeResult(projects, rooms)


def extract_domtut_class(card: Any) -> str | None:
    labels = [clean_text(x.get_text(" ", strip=True)) for x in card.select(".label-list a, .label")]
    labels = [label for label in labels if label]
    return labels[0] if labels else None


def extract_domtut_district(text: str) -> str | None:
    known = [
        "Olmazor",
        "Bektemir",
        "Chilonzor",
        "Mirobod",
        "Mirzo Ulug'bek",
        "Yakkasaroy",
        "Yashnobod",
        "Yunusobod",
        "Yangixayot",
        "Sergeli",
        "Shayxontohur",
        "Uchtepa",
        "Parkent",
        "Kibray",
        "Zangiota",
    ]
    for district in known:
        if re.search(rf"\b{re.escape(district)}\b", text, flags=re.IGNORECASE):
            return district
    return None


def extract_domtut_completion(text: str) -> str | None:
    match = re.search(r"(Topshirildi\s+\d{4}|Topshirilishi\s+[^,]+)", text)
    return clean_text(match.group(1)) if match else None


def extract_domtut_address(text: str) -> str | None:
    match = re.search(r"TJ\s+«[^»]+»\s+(?:To'lov rejasi\s+)?(.+?)(?=\s+\d+\s*-\s*xona| Kelishilgan|$)", text)
    if not match:
        return None
    address = clean_text(match.group(1))
    if not address:
        return None
    address = re.sub(r"^(Qulaylik|Biznes|Premium)\s+", "", address)
    return address


def parse_uzs_amount(text: str) -> int | None:
    value = to_float(text)
    if value is None:
        return None
    lowered = text.lower()
    if "mlrd" in lowered:
        return int(round(value * 1_000_000_000))
    if "mln" in lowered:
        return int(round(value * 1_000_000))
    return int(round(value))


def extract_domtut_room_prices(text: str) -> list[dict[str, Any]]:
    pattern = re.compile(
        r"(?P<rooms>\d+)\s*-\s*xona\s+(?P<area>\d+(?:[.,]\d+)?)\s*m²\s+(?:dan\s+)?(?P<price>(?:\d+(?:[.,]\d+)?\s*(?:mln|mlrd)|Kelishilgan))",
        flags=re.IGNORECASE,
    )
    entries = []
    for match in pattern.finditer(text):
        price_text = match.group("price")
        entries.append(
            {
                "rooms": to_int(match.group("rooms")),
                "area": to_float(match.group("area")),
                "total_uzs": None if "Kelishilgan" in price_text else parse_uzs_amount(price_text),
            }
        )
    return entries


CITY_MAP = {
    "Toshkent": "Toshkent shahri",
    "город Ташкент": "Toshkent shahri",
    "Ташкентская область": "Toshkent viloyati",
    "Андижанская область": "Andijon viloyati",
    "Бухарская область": "Buxoro viloyati",
    "Джиззакская область": "Jizzax viloyati",
    "Навоийская область": "Navoiy viloyati",
    "Наманганская область": "Namangan viloyati",
    "Самаркандская область": "Samarqand viloyati",
    "Сырдарьинская область": "Sirdaryo viloyati",
    "Ферганская область": "Farg'ona viloyati",
}


DISTRICT_MAP = {
    "Алмазарский район": "Olmazor tumani",
    "Бектемирский район": "Bektemir tumani",
    "Мирабадский район": "Mirobod tumani",
    "Мирзо-Улугбекский район": "Mirzo Ulug'bek tumani",
    "Сергелийский район": "Sergeli tumani",
    "Учтепинский район": "Uchtepa tumani",
    "Шайхантахурский район": "Shayxontohur tumani",
    "Чиланзарский район": "Chilonzor tumani",
    "Юнусабадский район": "Yunusobod tumani",
    "Яккасарайский район": "Yakkasaroy tumani",
    "Янгихаятский район": "Yangihayot tumani",
    "Яшнабадский район": "Yashnobod tumani",
    "Mirobod": "Mirobod tumani",
    "Mirzo Ulug'bek": "Mirzo Ulug'bek tumani",
    "Sergeli": "Sergeli tumani",
    "Shayxontohur": "Shayxontohur tumani",
    "Shayxontoxur tumani": "Shayxontohur tumani",
    "Uchtepa": "Uchtepa tumani",
    "Yakkasaroy": "Yakkasaroy tumani",
    "Yashnobod": "Yashnobod tumani",
    "Yunusobod": "Yunusobod tumani",
    "Yangixayot": "Yangihayot tumani",
    "Yangixayot tumani": "Yangihayot tumani",
    "город Андижан": "Andijon shahri",
    "город Бухара": "Buxoro shahri",
    "город Гулистан": "Guliston shahri",
    "город Джиззак": "Jizzax shahri",
    "город Зарафшан": "Zarafshon shahri",
    "город Навои": "Navoiy shahri",
    "город Наманган": "Namangan shahri",
    "город Чирчик": "Chirchiq shahri",
    "Ургут": "Urgut tumani",
}


CITY_MAP.update(
    {
        "Ташкент": "Toshkent shahri",
        "город Ташкент": "Toshkent shahri",
        "Город Ташкент": "Toshkent shahri",
        "Ташкентская область": "Toshkent viloyati",
        "Ташкенсткая область": "Toshkent viloyati",
        "Андижанская область": "Andijon viloyati",
        "Бухарская область": "Buxoro viloyati",
        "Джизакская область": "Jizzax viloyati",
        "Джиззакская область": "Jizzax viloyati",
        "Кашкадарьинская область": "Qashqadaryo viloyati",
        "Навоийская область": "Navoiy viloyati",
        "Наманганская область": "Namangan viloyati",
        "Самаркандская область": "Samarqand viloyati",
        "Самарқанд вилояти": "Samarqand viloyati",
        "Сирдарьинская область": "Sirdaryo viloyati",
        "Сурхандарьинская область": "Surxondaryo viloyati",
        "Ферганская область": "Farg'ona viloyati",
        "Хорезмская область": "Xorazm viloyati",
        "Qoraqalpogâ€˜iston Respublikasi": "Qoraqalpog'iston Respublikasi",
    }
)


DISTRICT_MAP.update(
    {
        "Алмазарский район": "Olmazor tumani",
        "Бектемирский район": "Bektemir tumani",
        "Мирабадский район": "Mirobod tumani",
        "Мирзо-Улугбекский район": "Mirzo Ulug'bek tumani",
        "Сергелийский район": "Sergeli tumani",
        "Учтепинский район": "Uchtepa tumani",
        "Шайхантахурский район": "Shayxontohur tumani",
        "Чиланзарский район": "Chilonzor tumani",
        "Юнусабадский район": "Yunusobod tumani",
        "Яккасарайский район": "Yakkasaroy tumani",
        "Янгихаятский район": "Yangihayot tumani",
        "Яшнабадский район": "Yashnobod tumani",
        "Chilonzor": "Chilonzor tumani",
        "Bektemir": "Bektemir tumani",
        "Olmazor": "Olmazor tumani",
        "Zangiota": "Zangiota tumani",
        "Sirg'ali tumani": "Sergeli tumani",
        "Chirchiq shahar": "Chirchiq shahri",
        "Зангиатинский район": "Zangiota tumani",
        "Ташкентский район": "Toshkent tumani",
        "Бостанлыкский район": "Bo'stonliq tumani",
        "Бостанлыксий район": "Bo'stonliq tumani",
        "Кибрайский район": "Qibray tumani",
        "Юкоричирчикский район": "Yuqorichirchiq tumani",
        "Юкарычирчикский район": "Yuqorichirchiq tumani",
        "Куйичирчикский район": "Quyi Chirchiq tumani",
        "Янгиюльский район": "Yangiyo'l tumani",
        "Бекабадский район": "Bekobod tumani",
        "Пскентский район": "Piskent tumani",
        "город Ангрен": "Angren shahri",
        "город Алмалык": "Olmaliq shahri",
        "город Бекабад": "Bekobod shahri",
        "город Нурафшан": "Nurafshon shahri",
        "город Нуравшан": "Nurafshon shahri",
        "город Янгиюль": "Yangiyo'l shahri",
        "город Чирчик": "Chirchiq shahri",
        "Келес": "Toshkent tumani",
        "Андижанский район": "Andijon tumani",
        "Асакинский район": "Asaka tumani",
        "Жалакудукский район": "Jalaquduq tumani",
        "Гиждуванский район": "G'ijduvon tumani",
        "город Фергана": "Farg'ona shahri",
        "город Коканд": "Qo'qon shahri",
        "город Маргилан": "Marg'ilon shahri",
        "Карманинский район": "Karmana tumani",
        "Учкудукский район": "Uchquduq tumani",
        "город Самарканд": "Samarqand shahri",
        "Самаркандский район": "Samarqand tumani",
        "Самарқанд тумани": "Samarqand tumani",
        "Тайлоқ тумани": "Tayloq tumani",
        "Ургутский район": "Urgut tumani",
        "Зааминский район": "Zomin tumani",
        "город Джизак": "Jizzax shahri",
        "город Джиззак": "Jizzax shahri",
        "город Карши": "Qarshi shahri",
        "Денауский район": "Denov tumani",
        "город Термез": "Termiz shahri",
        "город Ургенч": "Urganch shahri",
    }
)


VALID_CITY_VALUES = {
    "Andijon viloyati",
    "Buxoro viloyati",
    "Farg'ona viloyati",
    "Jizzax viloyati",
    "Namangan viloyati",
    "Navoiy viloyati",
    "Qashqadaryo viloyati",
    "Qoraqalpog'iston Respublikasi",
    "Samarqand viloyati",
    "Sirdaryo viloyati",
    "Surxondaryo viloyati",
    "Toshkent shahri",
    "Toshkent viloyati",
    "Xorazm viloyati",
}


VALID_DISTRICTS_BY_CITY = {
    "Toshkent shahri": {
        "Bektemir tumani",
        "Chilonzor tumani",
        "Mirobod tumani",
        "Mirzo Ulug'bek tumani",
        "Olmazor tumani",
        "Sergeli tumani",
        "Shayxontohur tumani",
        "Uchtepa tumani",
        "Yakkasaroy tumani",
        "Yangihayot tumani",
        "Yashnobod tumani",
        "Yunusobod tumani",
    },
    "Toshkent viloyati": {
        "Angren shahri",
        "Bekobod shahri",
        "Bekobod tumani",
        "Bo'stonliq tumani",
        "Chirchiq shahri",
        "Nurafshon shahri",
        "Olmaliq shahri",
        "Piskent tumani",
        "Qibray tumani",
        "Quyi Chirchiq tumani",
        "Toshkent tumani",
        "Yangiyo'l shahri",
        "Yangiyo'l tumani",
        "Yuqorichirchiq tumani",
        "Zangiota tumani",
    },
    "Andijon viloyati": {"Andijon shahri", "Andijon tumani", "Asaka tumani", "Jalaquduq tumani"},
    "Buxoro viloyati": {"Buxoro shahri", "G'ijduvon tumani"},
    "Farg'ona viloyati": {"Farg'ona shahri", "Marg'ilon shahri", "Qo'qon shahri"},
    "Jizzax viloyati": {"Jizzax shahri", "Zomin tumani"},
    "Namangan viloyati": {"Namangan shahri"},
    "Navoiy viloyati": {
        "Karmana tumani",
        "Navoiy shahri",
        "Qiziltepa tumani",
        "Uchquduq tumani",
        "Zarafshon shahri",
    },
    "Qashqadaryo viloyati": {"Qarshi shahri"},
    "Samarqand viloyati": {
        "Kattaqurg'on tumani",
        "Samarqand shahri",
        "Samarqand tumani",
        "Tayloq tumani",
        "Urgut tumani",
    },
    "Sirdaryo viloyati": {"Guliston shahri"},
    "Surxondaryo viloyati": {"Denov tumani", "Termiz shahri"},
    "Xorazm viloyati": {"Urganch shahri"},
}


DISTRICT_TO_CITY = {
    district: city
    for city, districts in VALID_DISTRICTS_BY_CITY.items()
    for district in districts
}


LOCAL_CITY_TO_LOCATION = {
    "Chirchiq": ("Toshkent viloyati", "Chirchiq shahri"),
    "Jizzax": ("Jizzax viloyati", "Jizzax shahri"),
    "Qarshi": ("Qashqadaryo viloyati", "Qarshi shahri"),
    "Qiziltepa": ("Navoiy viloyati", "Qiziltepa tumani"),
    "Yangiyo'l": ("Toshkent viloyati", "Yangiyo'l shahri"),
}


ANOMALY_LOCATION_TOKENS = (
    "aholi punkti",
    "mahalla",
    "mahalla fuqarolar",
    "tjm",
    "mitti",
    "пос.",
    "mfy",
    "мфй",
)


def normalize_location_text(value: Any) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    return (
        text.replace("`", "'")
        .replace("‘", "'")
        .replace("’", "'")
        .replace("ʻ", "'")
        .replace("ʼ", "'")
        .replace("â€˜", "'")
        .replace("â€™", "'")
    )


def is_location_anomaly(value: Any) -> bool:
    text = normalize_location_text(value)
    if not text:
        return False
    lowered = text.lower()
    return any(token in lowered for token in ANOMALY_LOCATION_TOKENS)


def normalize_city(value: Any) -> str | None:
    text = normalize_location_text(value)
    if not text:
        return None
    return CITY_MAP.get(text, text)


def normalize_district(value: Any) -> str | None:
    text = normalize_location_text(value)
    if not text:
        return None
    return DISTRICT_MAP.get(text, text)


def normalize_location_pair(city_value: Any, district_value: Any) -> tuple[str | None, str | None, bool, str]:
    raw_city = normalize_location_text(city_value)
    raw_district = normalize_location_text(district_value)
    city = normalize_city(raw_city)
    district = normalize_district(raw_district)

    if raw_city in LOCAL_CITY_TO_LOCATION:
        city, inferred_district = LOCAL_CITY_TO_LOCATION[raw_city]
        if not district or is_location_anomaly(raw_district) or district not in DISTRICT_TO_CITY:
            district = inferred_district

    if district in DISTRICT_TO_CITY:
        expected_city = DISTRICT_TO_CITY[district]
        if city != expected_city:
            city = expected_city
        return city, district, True, "ok"

    if is_location_anomaly(district):
        district = None

    if city not in VALID_CITY_VALUES:
        return None, None, False, "invalid_city"

    if district:
        return city, None, False, "district_removed"

    return city, None, False, "city_only"


def clean_location_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    if frame.empty or "city" not in frame.columns or "district" not in frame.columns:
        return frame, {}

    cleaned = frame.copy()
    cities = []
    districts = []
    valid_flags = []
    issues = []
    for city_value, district_value in zip(cleaned["city"], cleaned["district"]):
        city, district, valid, issue = normalize_location_pair(city_value, district_value)
        cities.append(city)
        districts.append(district)
        valid_flags.append(valid)
        issues.append(issue)

    cleaned["city"] = cities
    cleaned["district"] = districts
    cleaned["location_valid"] = valid_flags
    cleaned["location_issue"] = issues
    issue_counts = cleaned["location_issue"].value_counts(dropna=False).to_dict()
    return cleaned, {str(key): int(value) for key, value in issue_counts.items()}


def enrich_project_prices(projects: pd.DataFrame) -> pd.DataFrame:
    if projects.empty:
        return projects
    numeric_cols = [
        "price_total_min_uzs",
        "price_total_max_uzs",
        "price_total_min_usd",
        "price_total_max_usd",
        "price_per_sqm_min_uzs",
        "price_per_sqm_min_usd",
        "min_area_sqm",
        "max_area_sqm",
    ]
    for col in numeric_cols:
        if col in projects.columns:
            projects[col] = pd.to_numeric(projects[col], errors="coerce")

    mask = projects["price_per_sqm_min_uzs"].isna() & projects["price_total_min_uzs"].notna() & projects["min_area_sqm"].gt(0)
    projects.loc[mask, "price_per_sqm_min_uzs"] = (
        projects.loc[mask, "price_total_min_uzs"] / projects.loc[mask, "min_area_sqm"]
    ).round()

    mask = projects["price_total_min_uzs"].isna() & projects["price_per_sqm_min_uzs"].notna() & projects["min_area_sqm"].gt(0)
    projects.loc[mask, "price_total_min_uzs"] = (
        projects.loc[mask, "price_per_sqm_min_uzs"] * projects.loc[mask, "min_area_sqm"]
    ).round()

    mask = projects["price_per_sqm_min_uzs"].notna() & projects["price_per_sqm_min_uzs"].lt(1_000_000)
    projects.loc[mask, "price_per_sqm_min_uzs"] = pd.NA
    projects["price_available"] = projects[
        ["price_per_sqm_min_uzs", "price_total_min_uzs", "price_total_min_usd"]
    ].notna().any(axis=1)
    return projects


def sanitize_room_prices(room_prices: pd.DataFrame) -> pd.DataFrame:
    if room_prices.empty:
        return room_prices
    for col in ["rooms", "min_area_sqm", "min_total_price_uzs", "min_total_price_usd", "price_per_sqm_uzs", "price_per_sqm_usd"]:
        if col in room_prices.columns:
            room_prices[col] = pd.to_numeric(room_prices[col], errors="coerce")
    room_prices = room_prices[room_prices["rooms"].between(0, 8, inclusive="both")]
    mask = room_prices["price_per_sqm_uzs"].notna() & room_prices["price_per_sqm_uzs"].lt(1_000_000)
    room_prices.loc[mask, "price_per_sqm_uzs"] = pd.NA
    return room_prices


def normalize_and_save(results: list[ScrapeResult]) -> tuple[pd.DataFrame, pd.DataFrame]:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    projects = pd.DataFrame([row for result in results for row in result.projects])
    room_prices = pd.DataFrame([row for result in results for row in result.room_prices])
    location_summary: dict[str, Any] = {
        "projects_before_location_filter": int(len(projects)),
        "room_rows_before_location_filter": int(len(room_prices)),
        "project_location_issues": {},
        "room_location_issues": {},
        "projects_dropped_invalid_location": 0,
        "room_rows_dropped_invalid_location": 0,
    }

    if not projects.empty:
        projects, project_location_issues = clean_location_frame(projects)
        location_summary["project_location_issues"] = project_location_issues
        before_filter = len(projects)
        projects = projects[projects["location_valid"]].copy()
        location_summary["projects_dropped_invalid_location"] = int(before_filter - len(projects))
        projects = enrich_project_prices(projects)
        projects = projects.drop_duplicates(subset=["source", "source_id"], keep="first")
        projects = projects.sort_values(["source", "city", "district", "project_name"], na_position="last")
    if not room_prices.empty:
        room_prices, room_location_issues = clean_location_frame(room_prices)
        location_summary["room_location_issues"] = room_location_issues
        room_prices = sanitize_room_prices(room_prices)
        before_filter = len(room_prices)
        if not projects.empty:
            valid_project_keys = set(zip(projects["source"], projects["source_id"].astype(str)))
            room_keys = list(zip(room_prices["source"], room_prices["source_id"].astype(str)))
            room_prices = room_prices[[key in valid_project_keys for key in room_keys]].copy()
        room_prices = room_prices[room_prices["location_valid"]].copy()
        location_summary["room_rows_dropped_invalid_location"] = int(before_filter - len(room_prices))
        room_prices = room_prices.drop_duplicates(
            subset=["source", "source_id", "rooms", "min_area_sqm", "min_total_price_uzs", "min_total_price_usd"],
            keep="first",
        )
        room_prices = room_prices.sort_values(["source", "city", "district", "project_name", "rooms"], na_position="last")

    projects.to_csv(PROCESSED_DIR / "projects.csv", index=False, encoding="utf-8-sig")
    room_prices.to_csv(PROCESSED_DIR / "room_prices.csv", index=False, encoding="utf-8-sig")

    summary = {
        "snapshot_utc": SNAPSHOT_UTC,
        "projects_total": int(len(projects)),
        "room_price_rows_total": int(len(room_prices)),
        "projects_by_source": projects["source"].value_counts(dropna=False).to_dict() if not projects.empty else {},
        "room_rows_by_source": room_prices["source"].value_counts(dropna=False).to_dict() if not room_prices.empty else {},
        "projects_with_price": int(projects["price_available"].fillna(False).sum()) if not projects.empty else 0,
        "location_quality": location_summary,
    }
    db_path = save_snapshot(projects, room_prices, summary)
    summary["database_path"] = str(db_path)
    try:
        summary["postgres"] = save_snapshot_postgres(projects, room_prices, summary)
    except Exception as exc:
        summary["postgres"] = {"enabled": True, "saved": False, "error": str(exc)}
    (PROCESSED_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return projects, room_prices


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    results = []
    for name, fetcher in [
        ("uysot", fetch_uysot),
        ("salomuy", fetch_salomuy),
        ("yangiuylar", fetch_yangiuylar),
        ("domtut", fetch_domtut),
    ]:
        print(f"Fetching {name}...")
        try:
            results.append(fetcher())
        except Exception as exc:
            print(f"WARNING: {name} failed: {exc}")
    projects, room_prices = normalize_and_save(results)
    print(f"Saved {len(projects)} projects and {len(room_prices)} room-level rows.")
    print(f"Output: {PROCESSED_DIR}")


SNAPSHOT_UTC = now_iso()


if __name__ == "__main__":
    main()
