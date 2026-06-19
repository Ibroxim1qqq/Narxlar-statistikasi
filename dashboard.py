from __future__ import annotations

import json
import re
import sqlite3
from html import escape
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from database import DB_PATH, database_summary, load_latest_snapshot, quote_identifier
from postgres_database import (
    load_latest_snapshot_postgres,
    postgres_enabled,
    postgres_summary,
    postgres_table_preview,
)


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "processed"
PROJECTS_CSV = DATA_DIR / "projects.csv"
ROOMS_CSV = DATA_DIR / "room_prices.csv"
SUMMARY_JSON = DATA_DIR / "summary.json"

NUMERIC_COLUMNS = {
    "price_total_min_uzs",
    "price_total_max_uzs",
    "price_total_min_usd",
    "price_total_max_usd",
    "price_per_sqm_min_uzs",
    "price_per_sqm_min_usd",
    "min_total_price_uzs",
    "min_total_price_usd",
    "price_per_sqm_uzs",
    "price_per_sqm_usd",
    "min_area_sqm",
    "max_area_sqm",
    "latitude",
    "longitude",
    "rooms",
}

COLOR_SEQUENCE = ["#0f766e", "#16a34a", "#0891b2", "#2563eb", "#be123c", "#52525b"]
BAND_ORDER = ["Value", "Mid-market", "Upper-mid", "Premium", "Ultra-prime", "Narx yo'q"]
BAND_COLORS = {
    "Value": "#16a34a",
    "Mid-market": "#0f766e",
    "Upper-mid": "#0891b2",
    "Premium": "#2563eb",
    "Ultra-prime": "#be123c",
    "Narx yo'q": "#71717a",
}

CITY_RENAMES = {
    "Самарқанд вилояти": "Samarqand viloyati",
    "Самаркандская область": "Samarqand viloyati",
    "Кашкадарьинская область": "Qashqadaryo viloyati",
    "Сурхандарьинская область": "Surxondaryo viloyati",
    "Джизакская область": "Jizzax viloyati",
    "Хорезмская область": "Xorazm viloyati",
    "Республика Каракалпакстан": "Qoraqalpog'iston",
}

DISTRICT_RENAMES = {
    "город Джизак": "Jizzax shahri",
    "город Самарканд": "Samarqand shahri",
    "город Карши": "Qarshi shahri",
    "город Термез": "Termiz shahri",
    "город Ургенч": "Urganch shahri",
}


st.set_page_config(page_title="O'zbekiston yangi uylar narxlari", layout="wide")


def apply_theme() -> None:
    st.markdown(
        """
        <style>
        .stApp {
            background: #f7faf8;
            color: #111827;
        }
        .block-container {
            max-width: 1480px;
            padding-top: 1.25rem;
            padding-bottom: 2rem;
        }
        h1 {
            font-size: 2.05rem;
            line-height: 1.18;
            margin-bottom: .25rem;
        }
        h2, h3 {
            color: #111827;
        }
        [data-testid="stMetric"] {
            background: #ffffff;
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            padding: 1rem;
        }
        .hero-band {
            border: 1px solid #dbe7df;
            background: linear-gradient(135deg, #ffffff 0%, #eef9f3 100%);
            border-radius: 8px;
            padding: 1.15rem 1.2rem;
            margin-bottom: 1rem;
        }
        .eyebrow {
            color: #0f766e;
            font-size: .78rem;
            font-weight: 700;
            text-transform: uppercase;
            margin-bottom: .35rem;
        }
        .hero-text {
            max-width: 980px;
            color: #374151;
            font-size: .98rem;
            margin-top: .4rem;
        }
        .metric-card {
            background: #ffffff;
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            padding: 1rem;
            min-height: 118px;
        }
        .metric-label {
            color: #6b7280;
            font-size: .78rem;
            font-weight: 700;
            text-transform: uppercase;
        }
        .metric-value {
            color: #111827;
            font-size: 1.55rem;
            line-height: 1.15;
            font-weight: 780;
            margin-top: .4rem;
        }
        .metric-detail {
            color: #4b5563;
            font-size: .84rem;
            margin-top: .45rem;
        }
        .insight {
            background: #ffffff;
            border: 1px solid #e5e7eb;
            border-left: 4px solid #0f766e;
            border-radius: 8px;
            padding: .9rem 1rem;
            min-height: 116px;
        }
        .insight-title {
            color: #0f766e;
            font-size: .78rem;
            font-weight: 800;
            text-transform: uppercase;
            margin-bottom: .3rem;
        }
        .insight-body {
            color: #111827;
            font-size: 1rem;
            font-weight: 650;
            line-height: 1.32;
        }
        .insight-note {
            color: #6b7280;
            font-size: .82rem;
            margin-top: .35rem;
        }
        .section-note {
            color: #4b5563;
            font-size: .92rem;
            margin-bottom: .7rem;
        }
        .stTabs [data-baseweb="tab-list"] {
            gap: .35rem;
        }
        .stTabs [data-baseweb="tab"] {
            background: #ffffff;
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            padding-left: .9rem;
            padding-right: .9rem;
        }
        .stTabs [aria-selected="true"] {
            border-color: #0f766e;
            color: #0f766e;
        }
        div[data-testid="stDataFrame"] {
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            overflow: hidden;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def price_band(value: Any) -> str:
    if pd.isna(value):
        return "Narx yo'q"
    value = float(value)
    if value < 8_000_000:
        return "Value"
    if value < 12_000_000:
        return "Mid-market"
    if value < 16_000_000:
        return "Upper-mid"
    if value < 22_000_000:
        return "Premium"
    return "Ultra-prime"


@st.cache_data
def load_data() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    db_meta: dict[str, Any] = {}
    if postgres_enabled():
        try:
            projects, rooms, pg_meta = load_latest_snapshot_postgres()
            if not projects.empty and not rooms.empty:
                return clean_loaded_data(projects, rooms, pg_meta)
            db_meta = {"postgres": pg_meta}
        except Exception as exc:
            db_meta = {"postgres_error": str(exc)}

    projects, rooms, sqlite_meta = load_latest_snapshot()
    db_meta.update(sqlite_meta)
    if projects.empty or rooms.empty:
        projects = pd.read_csv(PROJECTS_CSV, encoding="utf-8-sig")
        rooms = pd.read_csv(ROOMS_CSV, encoding="utf-8-sig")
        db_meta.update({"source": "csv_fallback"})

    return clean_loaded_data(projects, rooms, db_meta)


@st.cache_data
def load_summary() -> dict[str, Any]:
    if not SUMMARY_JSON.exists():
        return {}
    try:
        return json.loads(SUMMARY_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {}


def clean_loaded_data(
    projects: pd.DataFrame,
    rooms: pd.DataFrame,
    db_meta: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    for df in [projects, rooms]:
        for col in df.columns:
            if col in NUMERIC_COLUMNS or col.endswith("_uzs") or col.endswith("_usd"):
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "city" in df:
            df["city"] = df["city"].replace(CITY_RENAMES)
        if "district" in df:
            df["district"] = df["district"].replace(DISTRICT_RENAMES)

    projects["has_price"] = projects[
        ["price_per_sqm_min_uzs", "price_total_min_uzs", "price_total_min_usd"]
    ].notna().any(axis=1)
    projects["price_band"] = projects["price_per_sqm_min_uzs"].apply(price_band)
    projects["source"] = projects["source"].fillna("unknown").str.title()
    rooms["source"] = rooms["source"].fillna("unknown").str.title()
    rooms["room_label"] = rooms["rooms"].apply(room_label)
    return projects, rooms, db_meta


def room_label(value: Any) -> str:
    if pd.isna(value):
        return "n/a"
    rooms = int(value)
    return "Studio" if rooms == 0 else f"{rooms} xona"


def fmt_int(value: Any) -> str:
    if pd.isna(value):
        return "n/a"
    return f"{int(round(float(value))):,}".replace(",", " ")


def fmt_pct(value: Any) -> str:
    if pd.isna(value):
        return "n/a"
    return f"{float(value) * 100:.0f}%"


def fmt_money(value: Any, suffix: str = "so'm") -> str:
    if pd.isna(value):
        return "n/a"
    value = float(value)
    unit = f" {suffix}" if suffix else ""
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f} mlrd{unit}"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f} mln{unit}"
    return f"{value:,.0f}{unit}".replace(",", " ")


def fmt_mln(value: Any) -> str:
    if pd.isna(value):
        return "n/a"
    return f"{float(value) / 1_000_000:.1f}"


def snapshot_label(projects: pd.DataFrame) -> str:
    if projects.empty or projects["snapshot_utc"].dropna().empty:
        return "unknown"
    try:
        timestamp = pd.to_datetime(projects["snapshot_utc"].dropna().iloc[0], utc=True)
        return timestamp.tz_convert("Asia/Tashkent").strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(projects["snapshot_utc"].dropna().iloc[0])


def metric_card(label: str, value: str, detail: str = "") -> None:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{escape(label)}</div>
            <div class="metric-value">{escape(value)}</div>
            <div class="metric-detail">{escape(detail)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def insight_card(title: str, body: str, note: str = "") -> None:
    st.markdown(
        f"""
        <div class="insight">
            <div class="insight-title">{escape(title)}</div>
            <div class="insight-body">{escape(body)}</div>
            <div class="insight-note">{escape(note)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def polish(fig: go.Figure, height: int = 440) -> go.Figure:
    fig.update_layout(
        template="plotly_white",
        height=height,
        margin=dict(l=10, r=10, t=45, b=10),
        font=dict(family="Inter, Segoe UI, Arial", size=12, color="#111827"),
        colorway=COLOR_SEQUENCE,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    fig.update_xaxes(showgrid=True, gridcolor="#edf2f0", zeroline=False)
    fig.update_yaxes(showgrid=True, gridcolor="#edf2f0", zeroline=False)
    return fig


def city_stats(df: pd.DataFrame) -> pd.DataFrame:
    stats = (
        df.dropna(subset=["city", "price_per_sqm_min_uzs"])
        .groupby("city", as_index=False)
        .agg(
            median_sqm_uzs=("price_per_sqm_min_uzs", "median"),
            avg_sqm_uzs=("price_per_sqm_min_uzs", "mean"),
            low_sqm_uzs=("price_per_sqm_min_uzs", "min"),
            high_sqm_uzs=("price_per_sqm_min_uzs", "max"),
            median_total_uzs=("price_total_min_uzs", "median"),
            projects=("project_name", "count"),
            sources=("source", "nunique"),
        )
        .sort_values("median_sqm_uzs", ascending=False)
    )
    return stats


def district_stats(df: pd.DataFrame, min_projects: int) -> pd.DataFrame:
    stats = (
        df.dropna(subset=["city", "district", "price_per_sqm_min_uzs"])
        .groupby(["city", "district"], as_index=False)
        .agg(
            median_sqm_uzs=("price_per_sqm_min_uzs", "median"),
            avg_sqm_uzs=("price_per_sqm_min_uzs", "mean"),
            median_total_uzs=("price_total_min_uzs", "median"),
            projects=("project_name", "count"),
            sources=("source", "nunique"),
        )
    )
    return stats[stats["projects"] >= min_projects].sort_values("median_sqm_uzs", ascending=False)


def room_stats(df: pd.DataFrame) -> pd.DataFrame:
    stats = (
        df.dropna(subset=["rooms"])
        .groupby("rooms", as_index=False)
        .agg(
            median_total_uzs=("min_total_price_uzs", "median"),
            q25_total_uzs=("min_total_price_uzs", lambda x: x.quantile(0.25)),
            q75_total_uzs=("min_total_price_uzs", lambda x: x.quantile(0.75)),
            median_sqm_uzs=("price_per_sqm_uzs", "median"),
            median_area_sqm=("min_area_sqm", "median"),
            offers=("project_name", "count"),
        )
        .sort_values("rooms")
    )
    stats["room_label"] = stats["rooms"].apply(room_label)
    return stats


def source_quality(df: pd.DataFrame) -> pd.DataFrame:
    stats = (
        df.groupby("source", as_index=False)
        .agg(
            projects=("project_name", "count"),
            priced_projects=("has_price", "sum"),
            median_sqm_uzs=("price_per_sqm_min_uzs", "median"),
            cities=("city", "nunique"),
            districts=("district", "nunique"),
        )
        .sort_values("projects", ascending=False)
    )
    stats["price_coverage"] = stats["priced_projects"] / stats["projects"]
    return stats


def filter_projects(
    projects: pd.DataFrame,
    *,
    key: str,
    source: bool = True,
    city: bool = True,
    district: bool = False,
    segment: bool = False,
    price_range: bool = False,
    search: bool = False,
    only_priced_default: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    controls = st.container()
    with controls:
        filter_cols = st.columns(4)
        filtered = projects.copy()
        scope = projects.copy()

        with filter_cols[0]:
            if source:
                sources = sorted(projects["source"].dropna().unique())
                selected_sources = st.multiselect("Manba", sources, default=sources, key=f"{key}_source")
                filtered = filtered[filtered["source"].isin(selected_sources)]
                scope = scope[scope["source"].isin(selected_sources)]

        with filter_cols[1]:
            if city:
                city_options = sorted(filtered["city"].dropna().unique())
                selected_cities = st.multiselect("Shahar/viloyat", city_options, key=f"{key}_city")
                if selected_cities:
                    filtered = filtered[filtered["city"].isin(selected_cities)]
                    scope = scope[scope["city"].isin(selected_cities)]

        with filter_cols[2]:
            if district:
                district_options = sorted(filtered["district"].dropna().unique())
                selected_districts = st.multiselect("Tuman", district_options, key=f"{key}_district")
                if selected_districts:
                    filtered = filtered[filtered["district"].isin(selected_districts)]
                    scope = scope[scope["district"].isin(selected_districts)]
            elif segment:
                selected_segments = st.multiselect(
                    "Segment",
                    [band for band in BAND_ORDER if band in set(filtered["price_band"].dropna())],
                    key=f"{key}_segment",
                )
                if selected_segments:
                    filtered = filtered[filtered["price_band"].isin(selected_segments)]
                    scope = scope[scope["price_band"].isin(selected_segments)]

        with filter_cols[3]:
            only_priced = st.checkbox("Faqat narxi bor", value=only_priced_default, key=f"{key}_priced")

        if price_range:
            priced_values = filtered["price_per_sqm_min_uzs"].dropna()
            if not priced_values.empty:
                min_mln = int(max(0, priced_values.min() // 1_000_000))
                max_mln = int(priced_values.max() // 1_000_000 + 1)
                if max_mln > min_mln:
                    selected_range = st.slider(
                        "m2 narx diapazoni, mln so'm",
                        min_value=min_mln,
                        max_value=max_mln,
                        value=(min_mln, max_mln),
                        step=1,
                        key=f"{key}_price_range",
                    )
                    lower, upper = selected_range[0] * 1_000_000, selected_range[1] * 1_000_000
                    filtered = filtered[
                        filtered["price_per_sqm_min_uzs"].between(lower, upper, inclusive="both")
                    ]

        if search:
            query = st.text_input(
                "Loyiha/developer/qidirish",
                placeholder="Masalan: Nest, Yakkasaroy, Murad",
                key=f"{key}_search",
            )
            if query:
                searchable_cols = ["project_name", "developer", "city", "district", "address", "source"]
                search_blob = filtered[searchable_cols].fillna("").astype(str).agg(" ".join, axis=1)
                filtered = filtered[search_blob.str.contains(re.escape(query), case=False, na=False)]

    if only_priced:
        filtered = filtered[filtered["has_price"]]
    return filtered, scope


def matching_rooms(rooms: pd.DataFrame, projects: pd.DataFrame) -> pd.DataFrame:
    if projects.empty:
        return rooms.iloc[0:0].copy()
    keys = set(zip(projects["source"], projects["source_id"].astype(str)))
    room_keys = list(zip(rooms["source"], rooms["source_id"].astype(str)))
    return rooms[[key in keys for key in room_keys]].copy()


def filter_rooms(
    rooms: pd.DataFrame,
    projects: pd.DataFrame,
    *,
    key: str,
) -> pd.DataFrame:
    scoped_projects, _ = filter_projects(
        projects,
        key=f"{key}_project_scope",
        source=True,
        city=True,
        district=True,
        only_priced_default=True,
    )
    filtered = matching_rooms(rooms, scoped_projects)
    room_values = sorted(int(x) for x in filtered["rooms"].dropna().unique() if 0 <= int(x) <= 8)
    if room_values:
        labels = [room_label(x) for x in room_values]
        selected_labels = st.multiselect("Xona filteri", labels, key=f"{key}_rooms")
        if selected_labels:
            selected_rooms = {room_values[labels.index(label)] for label in selected_labels}
            filtered = filtered[filtered["rooms"].isin(selected_rooms)]
    return filtered


def overview_cards(projects: pd.DataFrame, rooms: pd.DataFrame, quality_scope: pd.DataFrame) -> None:
    cities = city_stats(projects)
    districts = district_stats(projects, 2)
    scope_total = len(quality_scope)
    priced_count = int(quality_scope["has_price"].sum()) if not quality_scope.empty else 0
    coverage = priced_count / scope_total if scope_total else float("nan")

    avg_sqm = projects["price_per_sqm_min_uzs"].mean()
    median_total = projects["price_total_min_uzs"].median()
    room2 = rooms[rooms["rooms"].eq(2)]["min_total_price_uzs"].median()
    top_city = cities.iloc[0] if not cities.empty else None
    cheap_city = cities.sort_values("median_sqm_uzs").iloc[0] if not cities.empty else None
    top_district = districts.iloc[0] if not districts.empty else None
    cheap_district = districts.sort_values("median_sqm_uzs").iloc[0] if not districts.empty else None

    first_row = st.columns(4)
    with first_row[0]:
        metric_card("Loyihalar", fmt_int(len(projects)), f"narx coverage {fmt_pct(coverage)}")
    with first_row[1]:
        metric_card("O'rtacha m2 narx", fmt_money(avg_sqm), "narxi bor loyihalar bo'yicha")
    with first_row[2]:
        metric_card("Median uy narxi", fmt_money(median_total), "min total price benchmark")
    with first_row[3]:
        metric_card("2 xona benchmark", fmt_money(room2), "eng likvid format")

    second_row = st.columns(4)
    with second_row[0]:
        metric_card(
            "Eng qimmat shahar",
            top_city["city"] if top_city is not None else "n/a",
            fmt_money(top_city["median_sqm_uzs"]) + "/m2" if top_city is not None else "",
        )
    with second_row[1]:
        metric_card(
            "Eng arzon shahar",
            cheap_city["city"] if cheap_city is not None else "n/a",
            fmt_money(cheap_city["median_sqm_uzs"]) + "/m2" if cheap_city is not None else "",
        )
    with second_row[2]:
        metric_card(
            "Premium tuman",
            top_district["district"] if top_district is not None else "n/a",
            fmt_money(top_district["median_sqm_uzs"]) + "/m2" if top_district is not None else "",
        )
    with second_row[3]:
        metric_card(
            "Value tuman",
            cheap_district["district"] if cheap_district is not None else "n/a",
            fmt_money(cheap_district["median_sqm_uzs"]) + "/m2" if cheap_district is not None else "",
        )


def city_bar(stats: pd.DataFrame, *, title: str, ascending: bool, height: int = 420) -> go.Figure:
    chart = stats.sort_values("median_sqm_uzs", ascending=ascending).head(10)
    chart = chart.sort_values("median_sqm_uzs")
    fig = px.bar(
        chart,
        x="median_sqm_uzs",
        y="city",
        orientation="h",
        color="projects",
        color_continuous_scale=["#d1fae5", "#0f766e"],
        text=chart["median_sqm_uzs"].map(fmt_mln),
        labels={"median_sqm_uzs": "Median m2, UZS", "city": "", "projects": "Loyiha"},
        title=title,
    )
    fig.update_traces(texttemplate="%{text} mln", textposition="outside", cliponaxis=False)
    return polish(fig, height)


def district_bar(stats: pd.DataFrame, *, title: str, ascending: bool, color: str, height: int = 420) -> go.Figure:
    chart = stats.sort_values("median_sqm_uzs", ascending=ascending).head(10)
    chart = chart.sort_values("median_sqm_uzs")
    fig = px.bar(
        chart,
        x="median_sqm_uzs",
        y="district",
        orientation="h",
        color_discrete_sequence=[color],
        text=chart["median_sqm_uzs"].map(fmt_mln),
        hover_data=["city", "projects"],
        labels={"median_sqm_uzs": "Median m2, UZS", "district": ""},
        title=title,
    )
    fig.update_traces(texttemplate="%{text} mln", textposition="outside", cliponaxis=False)
    return polish(fig, height)


def render_compact_map(projects: pd.DataFrame, *, title: str = "Loyihalar xaritada", height: int = 520) -> None:
    geo = projects.dropna(subset=["latitude", "longitude"]).copy()
    geo = geo[geo["latitude"].between(35, 46) & geo["longitude"].between(55, 75)]
    if geo.empty:
        st.info("Bu filtrda xarita uchun koordinata bor loyihalar yo'q.")
        return

    geo["map_size"] = geo["price_per_sqm_min_uzs"].fillna(geo["price_per_sqm_min_uzs"].median()).fillna(1)
    fig = px.scatter_map(
        geo,
        lat="latitude",
        lon="longitude",
        color="price_band",
        size="map_size",
        size_max=16,
        zoom=8,
        center={"lat": float(geo["latitude"].median()), "lon": float(geo["longitude"].median())},
        hover_name="project_name",
        hover_data={
            "source": True,
            "city": True,
            "district": True,
            "price_per_sqm_min_uzs": ":,.0f",
            "price_total_min_uzs": ":,.0f",
            "latitude": False,
            "longitude": False,
            "map_size": False,
        },
        color_discrete_map=BAND_COLORS,
        category_orders={"price_band": BAND_ORDER},
        map_style="open-street-map",
        title=title,
    )
    st.plotly_chart(polish(fig, height), width="stretch")


def render_overview(projects: pd.DataFrame, rooms: pd.DataFrame) -> None:
    st.markdown("### Umumiy bozor ko'rinishi")
    st.markdown(
        '<div class="section-note">Kirish sahifasi: hozirgi snapshot bozorini tez o\'qish uchun eng muhim kardlar, reytinglar va xarita.</div>',
        unsafe_allow_html=True,
    )
    filtered_projects, quality_scope = filter_projects(
        projects,
        key="overview",
        source=True,
        city=True,
        district=False,
        only_priced_default=True,
    )
    filtered_rooms = matching_rooms(rooms, filtered_projects)

    if filtered_projects.empty:
        st.warning("Bu filterlarda narxli loyiha qolmadi.")
        return

    overview_cards(filtered_projects, filtered_rooms, quality_scope)
    st.write("")

    cities = city_stats(filtered_projects)
    districts = district_stats(filtered_projects, 2)

    city_left, city_right = st.columns(2)
    with city_left:
        if cities.empty:
            st.info("Shaharlar reytingi uchun data yetarli emas.")
        else:
            st.plotly_chart(city_bar(cities, title="Eng qimmat shahar/viloyatlar", ascending=False), width="stretch")
    with city_right:
        if cities.empty:
            st.info("Arzon hududlar uchun data yetarli emas.")
        else:
            st.plotly_chart(city_bar(cities, title="Eng arzon shahar/viloyatlar", ascending=True), width="stretch")

    district_left, district_right = st.columns(2)
    with district_left:
        if districts.empty:
            st.info("Tumanlar reytingi uchun data yetarli emas.")
        else:
            st.plotly_chart(
                district_bar(districts, title="Eng qimmat tumanlar", ascending=False, color="#be123c"),
                width="stretch",
            )
    with district_right:
        if districts.empty:
            st.info("Value tumanlar uchun data yetarli emas.")
        else:
            st.plotly_chart(
                district_bar(districts, title="Eng arzon tumanlar", ascending=True, color="#0f766e"),
                width="stretch",
            )

    render_compact_map(filtered_projects, title="Umumiy xarita: narx segmentlari va joylashuv", height=560)


def filter_data(projects: pd.DataFrame, rooms: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, int]:
    with st.sidebar:
        st.header("Filter panel")
        sources = sorted(projects["source"].dropna().unique())
        source_filter = st.multiselect("Manba", sources, default=sources)

        scoped_projects = projects[projects["source"].isin(source_filter)].copy()
        scoped_rooms = rooms[rooms["source"].isin(source_filter)].copy()

        city_options = sorted(scoped_projects["city"].dropna().unique())
        city_filter = st.multiselect("Shahar/viloyat", city_options)
        if city_filter:
            scoped_projects = scoped_projects[scoped_projects["city"].isin(city_filter)]
            scoped_rooms = scoped_rooms[scoped_rooms["city"].isin(city_filter)]

        district_options = sorted(scoped_projects["district"].dropna().unique())
        district_filter = st.multiselect("Tuman/shahar", district_options)
        if district_filter:
            scoped_projects = scoped_projects[scoped_projects["district"].isin(district_filter)]
            scoped_rooms = scoped_rooms[scoped_rooms["district"].isin(district_filter)]

        quality_scope = scoped_projects.copy()
        only_priced = st.checkbox("Faqat narxi bor loyihalar", value=True)
        min_projects = st.slider("Tuman reytingi minimum loyiha", 1, 10, 2)

        priced_values = scoped_projects["price_per_sqm_min_uzs"].dropna()
        selected_price_range: tuple[int, int] | None = None
        if not priced_values.empty:
            min_mln = int(max(0, priced_values.min() // 1_000_000))
            max_mln = int(priced_values.max() // 1_000_000 + 1)
            if max_mln > min_mln:
                selected_price_range = st.slider(
                    "m2 narx diapazoni, mln so'm",
                    min_value=min_mln,
                    max_value=max_mln,
                    value=(min_mln, max_mln),
                    step=1,
                )

        room_values = sorted(int(x) for x in scoped_rooms["rooms"].dropna().unique() if 0 <= int(x) <= 8)
        room_options = [room_label(x) for x in room_values]
        selected_room_labels = st.multiselect("Xonalar", room_options)
        selected_rooms = {room_values[room_options.index(label)] for label in selected_room_labels}

        project_search = st.text_input("Loyiha/developer qidirish", placeholder="Masalan: Nest, Mirobod, Golden")

    filtered_projects = scoped_projects.copy()
    filtered_rooms = scoped_rooms.copy()

    if only_priced:
        filtered_projects = filtered_projects[filtered_projects["has_price"]]
        filtered_rooms = filtered_rooms[
            filtered_rooms["price_per_sqm_uzs"].notna()
            | filtered_rooms["min_total_price_uzs"].notna()
            | filtered_rooms["min_total_price_usd"].notna()
        ]

    if selected_price_range is not None:
        full_range = (int(priced_values.min() // 1_000_000), int(priced_values.max() // 1_000_000 + 1))
        if selected_price_range != full_range:
            lower, upper = selected_price_range[0] * 1_000_000, selected_price_range[1] * 1_000_000
            filtered_projects = filtered_projects[
                filtered_projects["price_per_sqm_min_uzs"].between(lower, upper, inclusive="both")
            ]
            filtered_rooms = filtered_rooms[
                filtered_rooms["price_per_sqm_uzs"].between(lower, upper, inclusive="both")
            ]

    if selected_rooms:
        filtered_rooms = filtered_rooms[filtered_rooms["rooms"].isin(selected_rooms)]

    if project_search:
        searchable_cols = ["project_name", "developer", "city", "district", "address", "source"]
        search_blob = filtered_projects[searchable_cols].fillna("").astype(str).agg(" ".join, axis=1)
        filtered_projects = filtered_projects[
            search_blob.str.contains(re.escape(project_search), case=False, na=False)
        ]

    return filtered_projects, filtered_rooms, quality_scope, min_projects


def render_header(projects: pd.DataFrame) -> None:
    snapshot = snapshot_label(projects)
    st.markdown(
        f"""
        <div class="hero-band">
            <div class="eyebrow">Current market intelligence</div>
            <h1>O'zbekiston yangi uylar narxlari dashboardi</h1>
            <div class="hero-text">
                Uysot, Salomuy, Yangiuylar va Domtut manbalaridan yig'ilgan hozirgi snapshot.
                Snapshot vaqti: <b>{escape(snapshot)} Asia/Tashkent</b>.
                Dashboard shahar, tuman, xona, manba va loyiha kesimida narx signalini tez o'qish uchun tuzilgan.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_kpis(projects: pd.DataFrame, rooms: pd.DataFrame, quality_scope: pd.DataFrame) -> None:
    scope_total = len(quality_scope)
    priced_projects = int(quality_scope["has_price"].sum()) if "has_price" in quality_scope else 0
    coverage = priced_projects / scope_total if scope_total else float("nan")
    median_sqm = projects["price_per_sqm_min_uzs"].median()
    median_total = projects["price_total_min_uzs"].median()
    two_room = rooms[rooms["rooms"].eq(2)]["min_total_price_uzs"].median()
    source_count = quality_scope["source"].nunique() if not quality_scope.empty else 0

    cols = st.columns(5)
    with cols[0]:
        metric_card("Komplekslar", fmt_int(len(projects)), f"{source_count} manba scope ichida")
    with cols[1]:
        metric_card("Narx coverage", fmt_pct(coverage), f"{fmt_int(priced_projects)} / {fmt_int(scope_total)} scope")
    with cols[2]:
        metric_card("Median m2", fmt_money(median_sqm), "loyiha-level median")
    with cols[3]:
        metric_card("Median min total", fmt_money(median_total), "eng kichik e'lon narxi")
    with cols[4]:
        metric_card("2 xona median", fmt_money(two_room), "xona-level rows bo'yicha")


def render_insights(projects: pd.DataFrame, rooms: pd.DataFrame, quality_scope: pd.DataFrame, min_projects: int) -> None:
    cities = city_stats(projects)
    districts = district_stats(projects, min_projects)
    rooms_view = room_stats(rooms)
    quality = source_quality(quality_scope) if not quality_scope.empty else pd.DataFrame()

    insight_columns = st.columns(4)
    with insight_columns[0]:
        if cities.empty:
            insight_card("Shahar signali", "Narxli shahar datasi yetarli emas")
        else:
            top = cities.iloc[0]
            insight_card(
                "Eng yuqori city median",
                f"{top['city']} - {fmt_money(top['median_sqm_uzs'])}/m2",
                f"{fmt_int(top['projects'])} loyiha asosida",
            )
    with insight_columns[1]:
        if districts.empty:
            insight_card("Tuman signali", "Tuman reytingi uchun data kam")
        else:
            top = districts.iloc[0]
            insight_card(
                "Premium tuman",
                f"{top['district']} - {fmt_money(top['median_sqm_uzs'])}/m2",
                f"{top['city']}, minimum {min_projects} loyiha",
            )
    with insight_columns[2]:
        if rooms_view.empty:
            insight_card("Xona iqtisodiyoti", "Xona kesimidagi data yo'q")
        else:
            room2 = rooms_view[rooms_view["rooms"].eq(2)]
            row = room2.iloc[0] if not room2.empty else rooms_view.iloc[0]
            insight_card(
                "Likvid format",
                f"{room_label(row['rooms'])}: {fmt_money(row['median_total_uzs'])}",
                f"median maydon {row['median_area_sqm']:.1f} m2",
            )
    with insight_columns[3]:
        if quality.empty:
            insight_card("Data ishonchliligi", "Manba statistikasi yo'q")
        else:
            best = quality.sort_values(["price_coverage", "projects"], ascending=[False, False]).iloc[0]
            insight_card(
                "Eng to'liq manba",
                f"{best['source']} - {fmt_pct(best['price_coverage'])} coverage",
                f"{fmt_int(best['projects'])} loyiha, {fmt_int(best['districts'])} hudud",
            )


def render_executive(projects: pd.DataFrame, rooms: pd.DataFrame, quality_scope: pd.DataFrame, min_projects: int) -> None:
    st.markdown("### Bozor pulsi")
    st.markdown(
        '<div class="section-note">Yuqori darajadagi savol: bozor qayerda qimmatlashgan, qayerda volume bor, va qaysi xona formati asosiy benchmark?</div>',
        unsafe_allow_html=True,
    )
    render_kpis(projects, rooms, quality_scope)
    st.write("")
    render_insights(projects, rooms, quality_scope, min_projects)

    left, right = st.columns([1.55, 1])
    with left:
        cities = city_stats(projects).head(12).sort_values("median_sqm_uzs")
        if cities.empty:
            st.info("Shahar bo'yicha m2 narx yetarli emas.")
        else:
            fig = px.bar(
                cities,
                x="median_sqm_uzs",
                y="city",
                orientation="h",
                color="projects",
                color_continuous_scale=["#d1fae5", "#0f766e"],
                text=cities["median_sqm_uzs"].map(lambda x: fmt_mln(x)),
                labels={"median_sqm_uzs": "Median m2 narx, UZS", "city": "", "projects": "Loyiha"},
                title="Shahar/viloyat bo'yicha premiumlik reytingi",
            )
            fig.update_traces(texttemplate="%{text} mln", textposition="outside", cliponaxis=False)
            st.plotly_chart(polish(fig, 500), width="stretch")

    with right:
        priced = projects.dropna(subset=["price_per_sqm_min_uzs"]).copy()
        if priced.empty:
            st.info("Narx taqsimoti uchun data yetarli emas.")
        else:
            fig = px.histogram(
                priced,
                x="price_per_sqm_min_uzs",
                color="price_band",
                category_orders={"price_band": BAND_ORDER},
                color_discrete_map=BAND_COLORS,
                nbins=34,
                labels={"price_per_sqm_min_uzs": "m2 narx, UZS", "count": "Loyiha"},
                title="m2 narx taqsimoti",
            )
            fig.update_xaxes(tickformat=",.0f")
            st.plotly_chart(polish(fig, 500), width="stretch")


def render_cities(projects: pd.DataFrame) -> None:
    st.markdown("### Shahar va viloyat benchmarklari")
    filtered_projects, _ = filter_projects(
        projects,
        key="cities",
        source=True,
        city=True,
        district=False,
        price_range=True,
        only_priced_default=True,
    )
    stats = city_stats(filtered_projects)
    if stats.empty:
        st.info("Bu filtrda shahar/viloyat kesimi uchun yetarli narx yo'q.")
        return

    left, right = st.columns(2)
    with left:
        st.plotly_chart(city_bar(stats, title="Eng qimmat shahar/viloyatlar", ascending=False, height=460), width="stretch")
    with right:
        st.plotly_chart(city_bar(stats, title="Eng arzon shahar/viloyatlar", ascending=True, height=460), width="stretch")

    table = stats.copy()
    table["median_m2_mln"] = table["median_sqm_uzs"] / 1_000_000
    table["avg_m2_mln"] = table["avg_sqm_uzs"] / 1_000_000
    table["median_total_mlrd"] = table["median_total_uzs"] / 1_000_000_000
    st.dataframe(
        table[["city", "projects", "sources", "median_m2_mln", "avg_m2_mln", "median_total_mlrd"]],
        width="stretch",
        hide_index=True,
        column_config={
            "city": "Hudud",
            "projects": "Loyiha",
            "sources": "Manba",
            "median_m2_mln": st.column_config.NumberColumn("Median m2, mln", format="%.1f"),
            "avg_m2_mln": st.column_config.NumberColumn("O'rtacha m2, mln", format="%.1f"),
            "median_total_mlrd": st.column_config.NumberColumn("Median uy narxi, mlrd", format="%.2f"),
        },
    )


def render_districts(projects: pd.DataFrame) -> None:
    st.markdown("### Tumanlar: premium va value zonalar")
    filtered_projects, _ = filter_projects(
        projects,
        key="districts",
        source=True,
        city=True,
        district=False,
        price_range=True,
        only_priced_default=True,
    )
    min_projects = st.slider("Reytingga kirishi uchun minimum loyiha", 1, 10, 2, key="districts_min_projects")
    stats = district_stats(filtered_projects, min_projects)
    if stats.empty:
        st.info("Bu filtrda tuman reytingi uchun yetarli narxli data yo'q.")
        return

    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            district_bar(stats, title="Premium tumanlar", ascending=False, color="#be123c", height=500),
            width="stretch",
        )
    with right:
        st.plotly_chart(
            district_bar(stats, title="Nisbatan arzon tumanlar", ascending=True, color="#0f766e", height=500),
            width="stretch",
        )

    table = stats.copy()
    table["median_m2_mln"] = table["median_sqm_uzs"] / 1_000_000
    table["median_total_mlrd"] = table["median_total_uzs"] / 1_000_000_000
    st.dataframe(
        table[["city", "district", "projects", "sources", "median_m2_mln", "median_total_mlrd"]],
        width="stretch",
        hide_index=True,
        column_config={
            "city": "Hudud",
            "district": "Tuman",
            "projects": "Loyiha",
            "sources": "Manba",
            "median_m2_mln": st.column_config.NumberColumn("Median m2, mln", format="%.1f"),
            "median_total_mlrd": st.column_config.NumberColumn("Median uy narxi, mlrd", format="%.2f"),
        },
    )


def render_rooms(rooms: pd.DataFrame, projects: pd.DataFrame) -> None:
    st.markdown("### Xonalar iqtisodiyoti")
    filtered_rooms = filter_rooms(rooms, projects, key="rooms")
    stats = room_stats(filtered_rooms)
    if stats.empty:
        st.info("Bu filtrda xona kesimidagi data yo'q.")
        return

    fig = go.Figure()
    fig.add_bar(
        x=stats["room_label"],
        y=stats["median_total_uzs"],
        name="Median min total",
        marker_color="#0f766e",
        text=stats["median_total_uzs"].map(lambda x: fmt_money(x, "")),
        textposition="outside",
    )
    fig.add_scatter(
        x=stats["room_label"],
        y=stats["median_area_sqm"],
        name="Median maydon, m2",
        mode="lines+markers",
        marker_color="#be123c",
        yaxis="y2",
    )
    fig.update_layout(
        title="Xona soni oshgani sari ticket size va maydon qanday o'zgaradi?",
        yaxis=dict(title="Median min total, UZS", tickformat=",.0f"),
        yaxis2=dict(title="Median maydon, m2", overlaying="y", side="right", showgrid=False),
    )
    st.plotly_chart(polish(fig, 500), width="stretch")

    table = stats.copy()
    table["median_total_mlrd"] = table["median_total_uzs"] / 1_000_000_000
    table["median_m2_mln"] = table["median_sqm_uzs"] / 1_000_000
    st.dataframe(
        table[["room_label", "offers", "median_area_sqm", "median_m2_mln", "median_total_mlrd"]],
        width="stretch",
        hide_index=True,
        column_config={
            "room_label": "Xona",
            "offers": "Taklif rows",
            "median_area_sqm": st.column_config.NumberColumn("Median maydon", format="%.1f"),
            "median_m2_mln": st.column_config.NumberColumn("Median m2, mln", format="%.1f"),
            "median_total_mlrd": st.column_config.NumberColumn("Median total, mlrd", format="%.2f"),
        },
    )


def render_map(projects: pd.DataFrame) -> None:
    st.markdown("### Geo ko'rinish va premium nuqtalar")
    filtered_projects, _ = filter_projects(
        projects,
        key="map",
        source=True,
        city=True,
        district=False,
        segment=True,
        only_priced_default=True,
    )
    geo = filtered_projects.dropna(subset=["latitude", "longitude"]).copy()
    geo = geo[geo["latitude"].between(35, 46) & geo["longitude"].between(55, 75)]
    if geo.empty:
        st.info("Bu filtrda latitude/longitude bor loyihalar topilmadi.")
        return

    render_compact_map(filtered_projects, title="Narx segmentlari xaritada", height=640)

    premium = (
        geo.dropna(subset=["price_per_sqm_min_uzs"])
        .sort_values("price_per_sqm_min_uzs", ascending=False)
        .head(15)
    )
    if not premium.empty:
        st.dataframe(
            premium[
                [
                    "project_name",
                    "source",
                    "city",
                    "district",
                    "price_band",
                    "price_per_sqm_min_uzs",
                    "price_total_min_uzs",
                    "source_url",
                ]
            ],
            width="stretch",
            hide_index=True,
            column_config={
                "project_name": "Loyiha",
                "source": "Manba",
                "city": "Hudud",
                "district": "Tuman",
                "price_band": "Segment",
                "price_per_sqm_min_uzs": st.column_config.NumberColumn("m2 narx", format="%d"),
                "price_total_min_uzs": st.column_config.NumberColumn("Min total", format="%d"),
                "source_url": st.column_config.LinkColumn("Link"),
            },
        )


def render_projects(projects: pd.DataFrame) -> None:
    st.markdown("### Loyiha-level deal table")
    filtered_projects, _ = filter_projects(
        projects,
        key="projects",
        source=True,
        city=True,
        district=True,
        price_range=True,
        search=True,
        only_priced_default=True,
    )
    if filtered_projects.empty:
        st.info("Bu filtrda loyiha topilmadi.")
        return

    sort_options = {
        "m2 qimmatdan arzonga": ("price_per_sqm_min_uzs", False),
        "m2 arzondan qimmatga": ("price_per_sqm_min_uzs", True),
        "min total qimmatdan arzonga": ("price_total_min_uzs", False),
        "min total arzondan qimmatga": ("price_total_min_uzs", True),
        "loyiha nomi": ("project_name", True),
    }
    sort_label = st.selectbox("Sort", list(sort_options.keys()), index=0)
    sort_col, ascending = sort_options[sort_label]
    table = filtered_projects.sort_values(sort_col, ascending=ascending, na_position="last").copy()
    table["m2_mln"] = table["price_per_sqm_min_uzs"] / 1_000_000
    table["min_total_mlrd"] = table["price_total_min_uzs"] / 1_000_000_000
    table["area_range"] = table.apply(
        lambda row: (
            f"{row['min_area_sqm']:.1f}-{row['max_area_sqm']:.1f}"
            if pd.notna(row["min_area_sqm"]) and pd.notna(row["max_area_sqm"])
            else "n/a"
        ),
        axis=1,
    )

    st.dataframe(
        table[
            [
                "project_name",
                "developer",
                "source",
                "city",
                "district",
                "price_band",
                "m2_mln",
                "min_total_mlrd",
                "price_total_min_usd",
                "area_range",
                "rooms_available",
                "source_url",
            ]
        ],
        width="stretch",
        hide_index=True,
        height=560,
        column_config={
            "project_name": "Loyiha",
            "developer": "Developer",
            "source": "Manba",
            "city": "Hudud",
            "district": "Tuman",
            "price_band": "Segment",
            "m2_mln": st.column_config.NumberColumn("m2, mln so'm", format="%.1f"),
            "min_total_mlrd": st.column_config.NumberColumn("Min total, mlrd", format="%.2f"),
            "price_total_min_usd": st.column_config.NumberColumn("Min total, USD", format="$%d"),
            "area_range": "Maydon",
            "rooms_available": "Xonalar",
            "source_url": st.column_config.LinkColumn("Link"),
        },
    )

    st.download_button(
        "Filtered projects CSV yuklab olish",
        data=table.to_csv(index=False).encode("utf-8-sig"),
        file_name="filtered_projects.csv",
        mime="text/csv",
    )


def render_quality(projects: pd.DataFrame) -> None:
    st.markdown("### Data sifati va coverage")
    quality_scope, _ = filter_projects(
        projects,
        key="quality",
        source=True,
        city=True,
        district=False,
        only_priced_default=False,
    )
    if quality_scope.empty:
        st.info("Data sifati uchun scope bo'sh.")
        return

    stats = source_quality(quality_scope)
    left, right = st.columns([1, 1.1])
    with left:
        fig = px.bar(
            stats.sort_values("projects"),
            x="projects",
            y="source",
            orientation="h",
            color="price_coverage",
            color_continuous_scale=["#fee2e2", "#0f766e"],
            text=stats.sort_values("projects")["price_coverage"].map(fmt_pct),
            labels={"projects": "Loyihalar", "source": "", "price_coverage": "Narx coverage"},
            title="Manbalar bo'yicha coverage",
        )
        fig.update_traces(textposition="outside", cliponaxis=False)
        st.plotly_chart(polish(fig, 430), width="stretch")
    with right:
        display = stats.copy()
        display["median_m2_mln"] = display["median_sqm_uzs"] / 1_000_000
        st.dataframe(
            display[["source", "projects", "priced_projects", "price_coverage", "median_m2_mln", "cities", "districts"]],
            width="stretch",
            hide_index=True,
            column_config={
                "source": "Manba",
                "projects": "Loyiha",
                "priced_projects": "Narxi bor",
                "price_coverage": st.column_config.ProgressColumn("Coverage", min_value=0, max_value=1, format="%.0f"),
                "median_m2_mln": st.column_config.NumberColumn("Median m2, mln", format="%.1f"),
                "cities": "Hudud",
                "districts": "Tuman",
            },
        )

    summary = load_summary()
    location_quality = summary.get("location_quality", {})
    if location_quality:
        st.markdown("### Location QA")
        location_cols = st.columns(4)
        with location_cols[0]:
            metric_card(
                "Raw projects",
                fmt_int(location_quality.get("projects_before_location_filter")),
                "scraperdan kelgan jami loyiha",
            )
        with location_cols[1]:
            metric_card(
                "Valid projects",
                fmt_int(len(projects)),
                "city+district tekshiruvdan o'tgan",
            )
        with location_cols[2]:
            metric_card(
                "Dropped anomalies",
                fmt_int(location_quality.get("projects_dropped_invalid_location", 0)),
                "noto'g'ri yoki ishonchsiz lokatsiya",
            )
        with location_cols[3]:
            metric_card(
                "Bad locations in DB",
                fmt_int(int((~projects.get("location_valid", pd.Series(True, index=projects.index))).sum())),
                "0 bo'lishi kerak",
            )

        issues = location_quality.get("project_location_issues", {})
        if issues:
            issue_frame = pd.DataFrame(
                [{"issue": issue, "rows": rows} for issue, rows in issues.items()]
            ).sort_values("rows", ascending=False)
            fig = px.bar(
                issue_frame,
                x="rows",
                y="issue",
                orientation="h",
                color_discrete_sequence=["#0f766e"],
                title="Location cleaning natijasi",
                labels={"rows": "Loyiha", "issue": ""},
            )
            st.plotly_chart(polish(fig, 300), width="stretch")

    missing = pd.DataFrame(
        {
            "field": [
                "price_per_sqm_min_uzs",
                "price_total_min_uzs",
                "developer",
                "district",
                "latitude",
                "longitude",
            ],
            "missing_share": [
                quality_scope[col].isna().mean() if col in quality_scope else 1 for col in [
                    "price_per_sqm_min_uzs",
                    "price_total_min_uzs",
                    "developer",
                    "district",
                    "latitude",
                    "longitude",
                ]
            ],
        }
    )
    fig = px.bar(
        missing.sort_values("missing_share"),
        x="missing_share",
        y="field",
        orientation="h",
        color_discrete_sequence=["#0891b2"],
        labels={"missing_share": "Missing share", "field": ""},
        title="Qaysi maydonlarda bo'sh qiymat ko'p?",
    )
    fig.update_xaxes(tickformat=".0%")
    st.plotly_chart(polish(fig, 380), width="stretch")

    st.markdown(
        """
        **Analyst caveats**

        - Bu real-time snapshot: developerlar va marketplace narxlarni tez o'zgartirishi mumkin.
        - Ayrim manbalar m2 narx beradi, ayrimlari umumiy min narx beradi. Xona-level taxminlar `price_basis` maydonida belgilangan.
        - Tarixiy trend uchun scraper har kuni yoki haftada schedule qilinib, har bir snapshot alohida saqlanishi kerak.
        - Valyuta taqqoslash uchun keyingi qadam: CBU kursi bilan USD/UZS normalizatsiya va real narx indeksini qo'shish.
        """
    )


def render_database() -> None:
    st.markdown("### Database")
    info = database_summary()
    pg_info = postgres_summary()
    if not info.get("exists"):
        st.info("Database hali yaratilmagan. `python scrape_prices.py` ishga tushganda `data/housing_prices.sqlite` paydo bo'ladi.")
        return

    metric_cols = st.columns(4)
    counts = info.get("counts", {})
    latest = info.get("latest")
    with metric_cols[0]:
        metric_card("Database", "SQLite", str(DB_PATH))
    with metric_cols[1]:
        metric_card("Snapshots", fmt_int(counts.get("snapshots", 0)), "har kuni bittadan qo'shiladi")
    with metric_cols[2]:
        metric_card("Project rows", fmt_int(counts.get("projects_history", 0)), "history jadvali")
    with metric_cols[3]:
        metric_card("Room rows", fmt_int(counts.get("room_prices_history", 0)), "history jadvali")

    st.markdown("**PostgreSQL status**")
    pg_cols = st.columns(4)
    pg_counts = pg_info.get("counts", {})
    with pg_cols[0]:
        status = "Connected" if pg_info.get("connected") else ("Configured" if pg_info.get("enabled") else "Off")
        metric_card("PostgreSQL", status, pg_info.get("dsn", "POSTGRES_DSN yo'q"))
    with pg_cols[1]:
        metric_card("PG snapshots", fmt_int(pg_counts.get("snapshots", 0)), "PostgreSQL history")
    with pg_cols[2]:
        metric_card("PG projects", fmt_int(pg_counts.get("projects_history", 0)), "projects_history")
    with pg_cols[3]:
        metric_card("PG room rows", fmt_int(pg_counts.get("room_prices_history", 0)), "room_prices_history")

    if pg_info.get("error"):
        st.warning(f"PostgreSQL ulanish xatosi: {pg_info['error']}")
    elif not pg_info.get("enabled"):
        st.info("PostgreSQL uchun `.env` ichida `POSTGRES_DSN` sozlang. Sozlansa dashboard PostgreSQL'dan o'qiydi.")

    st.markdown("**Foydalanadigan asosiy SQL viewlar**")
    st.code(
        """SELECT * FROM latest_projects;
SELECT * FROM latest_room_prices;
SELECT * FROM snapshots ORDER BY snapshot_date DESC;

SELECT city, COUNT(*) AS projects, AVG(price_per_sqm_min_uzs) AS avg_m2_uzs
FROM latest_projects
WHERE price_per_sqm_min_uzs IS NOT NULL
GROUP BY city
ORDER BY avg_m2_uzs DESC;""",
        language="sql",
    )

    with sqlite3.connect(DB_PATH) as conn:
        snapshots = pd.read_sql_query(
            """
            SELECT
                snapshot_date,
                snapshot_utc,
                projects_total,
                room_price_rows_total,
                projects_with_price
            FROM snapshots
            ORDER BY snapshot_utc DESC
            LIMIT 30
            """,
            conn,
        )
        source_counts = pd.read_sql_query(
            """
            SELECT source, COUNT(*) AS projects
            FROM latest_projects
            GROUP BY source
            ORDER BY projects DESC
            """,
            conn,
        )

        history_trend = pd.read_sql_query(
            """
            SELECT
                snapshot_date,
                snapshot_utc,
                projects_total,
                room_price_rows_total,
                projects_with_price
            FROM snapshots
            ORDER BY snapshot_utc
            """,
            conn,
        )

    left, right = st.columns([1.2, 1])
    with left:
        st.markdown("**Oxirgi snapshotlar**")
        st.dataframe(snapshots, width="stretch", hide_index=True)
    with right:
        st.markdown("**Latest snapshot source coverage**")
        st.dataframe(source_counts, width="stretch", hide_index=True)

    if len(history_trend) > 1:
        trend = history_trend.copy()
        trend["snapshot_utc"] = pd.to_datetime(trend["snapshot_utc"], utc=True, errors="coerce")
        trend_long = trend.melt(
            id_vars="snapshot_utc",
            value_vars=["projects_total", "room_price_rows_total", "projects_with_price"],
            var_name="metric",
            value_name="rows",
        )
        fig = px.line(
            trend_long,
            x="snapshot_utc",
            y="rows",
            color="metric",
            markers=True,
            title="Kunlik snapshot o'sishi",
            labels={"snapshot_utc": "Snapshot vaqti", "rows": "Qatorlar", "metric": "Metric"},
        )
        st.plotly_chart(polish(fig, 360), width="stretch")

    st.markdown("**Database explorer**")
    st.markdown(
        '<div class="section-note">Jadval yoki view tanlang: dashboard ichidan SQL natijasini ko\'rasiz va CSV qilib olasiz.</div>',
        unsafe_allow_html=True,
    )
    sqlite_table_options = [
        table
        for table in info.get("tables", [])
        if table in {"snapshots", "projects_history", "room_prices_history", "latest_projects", "latest_room_prices"}
    ]
    postgres_table_options = [
        table
        for table in pg_info.get("tables", [])
        if table in {"snapshots", "projects_history", "room_prices_history", "latest_projects", "latest_room_prices"}
    ] if pg_info.get("connected") else []
    storage_options = []
    if postgres_table_options:
        storage_options.append("PostgreSQL")
    if sqlite_table_options:
        storage_options.append("SQLite")

    if storage_options:
        source_col, table_col, limit_col = st.columns([.75, 1.1, .55])
        with source_col:
            storage = st.selectbox("Storage", storage_options, index=0)
        table_options = postgres_table_options if storage == "PostgreSQL" else sqlite_table_options
        default_table = "latest_projects" if "latest_projects" in table_options else table_options[0]
        with table_col:
            selected_table = st.selectbox("Jadval/view", table_options, index=table_options.index(default_table))
        with limit_col:
            row_limit = st.number_input("Limit", min_value=20, max_value=5000, value=300, step=20)

        st.code(f"SELECT * FROM {selected_table} LIMIT {int(row_limit)};", language="sql")
        if storage == "PostgreSQL":
            preview = postgres_table_preview(selected_table, int(row_limit))
        else:
            with sqlite3.connect(DB_PATH) as conn:
                preview = pd.read_sql_query(
                    f"SELECT * FROM {quote_identifier(selected_table)} LIMIT ?",
                    conn,
                    params=(int(row_limit),),
                )
        st.dataframe(preview, width="stretch", hide_index=True, height=420)
        st.download_button(
            "Tanlangan jadvalni CSV yuklab olish",
            preview.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"{storage.lower()}_{selected_table}.csv",
            mime="text/csv",
        )

    if latest:
        st.caption(f"Latest snapshot: `{latest[1]}`. DB fayl: `{DB_PATH}`")


def main() -> None:
    apply_theme()

    if not PROJECTS_CSV.exists() or not ROOMS_CSV.exists():
        st.error("Avval `python scrape_prices.py` ni ishga tushiring.")
        st.stop()

    projects, rooms, db_meta = load_data()
    render_header(projects)

    if projects.empty and rooms.empty:
        st.warning("Data topilmadi. Avval scraper ishga tushiring.")
        return

    tabs = st.tabs(["Umumiy", "Shaharlar", "Tumanlar", "Xonalar", "Xarita", "Loyihalar", "Data quality", "Database"])
    with tabs[0]:
        render_overview(projects, rooms)
    with tabs[1]:
        render_cities(projects)
    with tabs[2]:
        render_districts(projects)
    with tabs[3]:
        render_rooms(rooms, projects)
    with tabs[4]:
        render_map(projects)
    with tabs[5]:
        render_projects(projects)
    with tabs[6]:
        render_quality(projects)
    with tabs[7]:
        render_database()

    st.caption(
        "Dashboard latest data'ni SQLite bazadagi latest_projects/latest_room_prices viewlaridan o'qiydi. "
        "CSV fayllar fallback/export uchun saqlanadi."
    )


if __name__ == "__main__":
    main()
