from __future__ import annotations

import re
from html import escape
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "processed"
PROJECTS_CSV = DATA_DIR / "projects.csv"
ROOMS_CSV = DATA_DIR / "room_prices.csv"

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
def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    projects = pd.read_csv(PROJECTS_CSV, encoding="utf-8-sig")
    rooms = pd.read_csv(ROOMS_CSV, encoding="utf-8-sig")

    for df in [projects, rooms]:
        for col in df.columns:
            if col in NUMERIC_COLUMNS or col.endswith("_uzs") or col.endswith("_usd"):
                df[col] = pd.to_numeric(df[col], errors="coerce")

    projects["has_price"] = projects[
        ["price_per_sqm_min_uzs", "price_total_min_uzs", "price_total_min_usd"]
    ].notna().any(axis=1)
    projects["price_band"] = projects["price_per_sqm_min_uzs"].apply(price_band)
    projects["source"] = projects["source"].fillna("unknown").str.title()
    rooms["source"] = rooms["source"].fillna("unknown").str.title()
    rooms["room_label"] = rooms["rooms"].apply(room_label)
    return projects, rooms


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
            st.plotly_chart(polish(fig, 500), use_container_width=True)

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
            st.plotly_chart(polish(fig, 500), use_container_width=True)


def render_cities(projects: pd.DataFrame) -> None:
    st.markdown("### Shahar va viloyat benchmarklari")
    stats = city_stats(projects)
    if stats.empty:
        st.info("Bu filtrda shahar/viloyat kesimi uchun yetarli narx yo'q.")
        return

    left, right = st.columns([1.2, 1])
    with left:
        fig = px.scatter(
            stats,
            x="projects",
            y="median_sqm_uzs",
            size="projects",
            color="sources",
            hover_name="city",
            color_continuous_scale=["#d1fae5", "#0f766e"],
            labels={
                "projects": "Loyihalar soni",
                "median_sqm_uzs": "Median m2 narx, UZS",
                "sources": "Manbalar",
            },
            title="Volume vs narx: qaysi hududda signal kuchli?",
        )
        fig.update_yaxes(tickformat=",.0f")
        st.plotly_chart(polish(fig, 470), use_container_width=True)
    with right:
        table = stats.copy()
        table["median_m2_mln"] = table["median_sqm_uzs"] / 1_000_000
        table["median_total_mlrd"] = table["median_total_uzs"] / 1_000_000_000
        st.dataframe(
            table[
                [
                    "city",
                    "projects",
                    "sources",
                    "median_m2_mln",
                    "median_total_mlrd",
                    "low_sqm_uzs",
                    "high_sqm_uzs",
                ]
            ],
            use_container_width=True,
            hide_index=True,
            column_config={
                "city": "Hudud",
                "projects": "Loyiha",
                "sources": "Manba",
                "median_m2_mln": st.column_config.NumberColumn("Median m2, mln", format="%.1f"),
                "median_total_mlrd": st.column_config.NumberColumn("Median min total, mlrd", format="%.2f"),
                "low_sqm_uzs": st.column_config.NumberColumn("Past m2", format="%d"),
                "high_sqm_uzs": st.column_config.NumberColumn("Yuqori m2", format="%d"),
            },
        )


def render_districts(projects: pd.DataFrame, min_projects: int) -> None:
    st.markdown("### Tumanlar: premium va value zonalar")
    stats = district_stats(projects, min_projects)
    if stats.empty:
        st.info("Bu filtrda tuman reytingi uchun yetarli narxli data yo'q.")
        return

    expensive = stats.head(12).sort_values("median_sqm_uzs")
    affordable = stats.tail(12).sort_values("median_sqm_uzs", ascending=False)
    left, right = st.columns(2)
    with left:
        fig = px.bar(
            expensive,
            x="median_sqm_uzs",
            y="district",
            orientation="h",
            color_discrete_sequence=["#be123c"],
            text=expensive["median_sqm_uzs"].map(fmt_mln),
            hover_data=["city", "projects", "sources"],
            labels={"median_sqm_uzs": "Median m2, UZS", "district": ""},
            title="Premium tumanlar",
        )
        fig.update_traces(texttemplate="%{text} mln", textposition="outside", cliponaxis=False)
        st.plotly_chart(polish(fig, 480), use_container_width=True)
    with right:
        fig = px.bar(
            affordable,
            x="median_sqm_uzs",
            y="district",
            orientation="h",
            color_discrete_sequence=["#0f766e"],
            text=affordable["median_sqm_uzs"].map(fmt_mln),
            hover_data=["city", "projects", "sources"],
            labels={"median_sqm_uzs": "Median m2, UZS", "district": ""},
            title="Nisbatan arzon zonalar",
        )
        fig.update_traces(texttemplate="%{text} mln", textposition="outside", cliponaxis=False)
        st.plotly_chart(polish(fig, 480), use_container_width=True)

    fig = px.scatter(
        stats,
        x="projects",
        y="median_sqm_uzs",
        color="city",
        size="projects",
        hover_name="district",
        labels={"projects": "Loyiha soni", "median_sqm_uzs": "Median m2, UZS"},
        title="Tumanlar narx-volume matritsasi",
    )
    fig.update_yaxes(tickformat=",.0f")
    st.plotly_chart(polish(fig, 520), use_container_width=True)


def render_rooms(rooms: pd.DataFrame) -> None:
    st.markdown("### Xonalar iqtisodiyoti")
    stats = room_stats(rooms)
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
    st.plotly_chart(polish(fig, 500), use_container_width=True)

    left, right = st.columns([1.25, 1])
    with left:
        plot_df = rooms.dropna(subset=["rooms", "price_per_sqm_uzs"]).copy()
        plot_df = plot_df[plot_df["rooms"].between(0, 7, inclusive="both")]
        if plot_df.empty:
            st.info("m2 narx boxplot uchun data yetarli emas.")
        else:
            plot_df["room_label"] = plot_df["rooms"].apply(room_label)
            fig = px.box(
                plot_df,
                x="room_label",
                y="price_per_sqm_uzs",
                color="room_label",
                color_discrete_sequence=COLOR_SEQUENCE,
                points="outliers",
                labels={"room_label": "Xona", "price_per_sqm_uzs": "m2 narx, UZS"},
                title="Har bir xona formatida m2 narx dispersiyasi",
            )
            fig.update_yaxes(tickformat=",.0f")
            fig.update_layout(showlegend=False)
            st.plotly_chart(polish(fig, 450), use_container_width=True)
    with right:
        table = stats.copy()
        table["median_total_mlrd"] = table["median_total_uzs"] / 1_000_000_000
        table["median_m2_mln"] = table["median_sqm_uzs"] / 1_000_000
        st.dataframe(
            table[["room_label", "offers", "median_area_sqm", "median_m2_mln", "median_total_mlrd"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "room_label": "Xona",
                "offers": "Rows",
                "median_area_sqm": st.column_config.NumberColumn("Median maydon", format="%.1f"),
                "median_m2_mln": st.column_config.NumberColumn("Median m2, mln", format="%.1f"),
                "median_total_mlrd": st.column_config.NumberColumn("Median total, mlrd", format="%.2f"),
            },
        )


def render_map(projects: pd.DataFrame) -> None:
    st.markdown("### Geo ko'rinish va premium nuqtalar")
    geo = projects.dropna(subset=["latitude", "longitude"]).copy()
    geo = geo[geo["latitude"].between(35, 46) & geo["longitude"].between(55, 75)]
    if geo.empty:
        st.info("Bu filtrda latitude/longitude bor loyihalar topilmadi.")
        return

    geo["map_size"] = geo["price_per_sqm_min_uzs"].fillna(geo["price_per_sqm_min_uzs"].median()).fillna(1)
    fig = px.scatter_mapbox(
        geo,
        lat="latitude",
        lon="longitude",
        color="price_band",
        size="map_size",
        size_max=18,
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
        title="Narx segmentlari xaritada",
    )
    fig.update_layout(mapbox_style="open-street-map")
    st.plotly_chart(polish(fig, 610), use_container_width=True)

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
            use_container_width=True,
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
    if projects.empty:
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
    table = projects.sort_values(sort_col, ascending=ascending, na_position="last").copy()
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
        use_container_width=True,
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


def render_quality(quality_scope: pd.DataFrame, filtered_projects: pd.DataFrame) -> None:
    st.markdown("### Data sifati va coverage")
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
        st.plotly_chart(polish(fig, 430), use_container_width=True)
    with right:
        display = stats.copy()
        display["median_m2_mln"] = display["median_sqm_uzs"] / 1_000_000
        st.dataframe(
            display[["source", "projects", "priced_projects", "price_coverage", "median_m2_mln", "cities", "districts"]],
            use_container_width=True,
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
    st.plotly_chart(polish(fig, 380), use_container_width=True)

    st.markdown(
        """
        **Analyst caveats**

        - Bu real-time snapshot: developerlar va marketplace narxlarni tez o'zgartirishi mumkin.
        - Ayrim manbalar m2 narx beradi, ayrimlari umumiy min narx beradi. Xona-level taxminlar `price_basis` maydonida belgilangan.
        - Tarixiy trend uchun scraper har kuni yoki haftada schedule qilinib, har bir snapshot alohida saqlanishi kerak.
        - Valyuta taqqoslash uchun keyingi qadam: CBU kursi bilan USD/UZS normalizatsiya va real narx indeksini qo'shish.
        """
    )


def main() -> None:
    apply_theme()

    if not PROJECTS_CSV.exists() or not ROOMS_CSV.exists():
        st.error("Avval `python scrape_prices.py` ni ishga tushiring.")
        st.stop()

    projects, rooms = load_data()
    render_header(projects)
    filtered_projects, filtered_rooms, quality_scope, min_projects = filter_data(projects, rooms)

    if filtered_projects.empty and filtered_rooms.empty:
        st.warning("Bu filter kombinatsiyasida data qolmadi. Filtrlarni kengaytiring.")
        return

    tabs = st.tabs(["Executive", "Shaharlar", "Tumanlar", "Xonalar", "Geo", "Loyihalar", "Data quality"])
    with tabs[0]:
        render_executive(filtered_projects, filtered_rooms, quality_scope, min_projects)
    with tabs[1]:
        render_cities(filtered_projects)
    with tabs[2]:
        render_districts(filtered_projects, min_projects)
    with tabs[3]:
        render_rooms(filtered_rooms)
    with tabs[4]:
        render_map(filtered_projects)
    with tabs[5]:
        render_projects(filtered_projects)
    with tabs[6]:
        render_quality(quality_scope, filtered_projects)

    st.caption(
        "Data files: data/processed/projects.csv va data/processed/room_prices.csv. "
        "Raw API/HTML javoblar data/raw papkasida saqlangan."
    )


if __name__ == "__main__":
    main()
