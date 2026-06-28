"""Streamlit UI / entry point (docs/03 STEP 7).

Run with:  streamlit run app/app.py

Two-phase design:
  * TREND ANALYSIS (ingest -> categorize -> aggregate -> forecast) runs AUTOMATICALLY
    from the live Socrata query.
  * RESOURCE ALLOCATION requires the planner to CONFIRM the deployable patrol units
    before the plan + AI narrative are produced.
"""
import logging
import os
import sys
from datetime import date

# Allow `streamlit run app/app.py` to resolve the `app` package.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import altair as alt
import pandas as pd
import streamlit as st

from app import analyze, categorize, config, db, ingest, suggest
from app.config import LOOKBACK_DAYS, PROACTIVE, TOTAL_PATROL_UNITS, VIOLENT

config.configure_logging()
logger = logging.getLogger(__name__)

NAVY = "#0b2a4a"
GOLD = "#c8a24a"


def _inject_css() -> None:
    st.markdown(
        f"""<style>
        .block-container {{ padding-top: 1.6rem; max-width: 1200px; }}
        [data-testid="stMetric"] {{
            background: #f6f8fb; border: 1px solid #e3e8ef;
            border-radius: 10px; padding: 14px 18px;
        }}
        [data-testid="stMetricValue"] {{ color: {NAVY}; font-weight: 700; }}
        [data-testid="stMetricLabel"] p {{ color: #5b6b80; }}
        h1, h2, h3 {{ color: {NAVY}; }}
        hr {{ border-color: {GOLD}; }}
        </style>""",
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------- #
# Charts (Altair — labeled axes, titles, tooltips)
# --------------------------------------------------------------------------- #
def _hbar(df: pd.DataFrame, x: str, y: str, xt: str, yt: str, title: str):
    return (
        alt.Chart(df)
        .mark_bar(color=NAVY, cornerRadiusEnd=3)
        .encode(
            x=alt.X(f"{x}:Q", title=xt),
            y=alt.Y(f"{y}:N", sort="-x", title=yt),
            tooltip=list(df.columns),
        )
        .properties(title=title, height=max(140, 30 * len(df)))
    )


def _category_mix(crime_df: pd.DataFrame) -> pd.DataFrame:
    """Calls per category (summing counts), sorted descending."""
    return (crime_df.groupby("category")["n"].sum()
            .reset_index(name="calls").sort_values("calls", ascending=False))


def _line(df: pd.DataFrame, title: str):
    return (
        alt.Chart(df)
        .mark_line(point=True, color=NAVY, strokeWidth=2)
        .encode(
            x=alt.X("iso_week:N", title="ISO week"),
            y=alt.Y("incidence:Q", title="Calls"),
            tooltip=["iso_week", "incidence"],
        )
        .properties(title=title, height=280)
    )


# --------------------------------------------------------------------------- #
# Pipeline (Phase 1 — automated, cached)
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner=False)
def run_analysis(days: int, iso_week: str):
    # `iso_week` is a cache-key input ONLY: ISO weeks roll over Monday 00:00, so when a new
    # week starts the key changes and the data is re-pulled automatically (see main()).
    raw = ingest.load_calls(days)
    cat = categorize.categorize(raw)
    agg = analyze.aggregate(cat)
    fc = analyze.forecast(agg)
    return raw, cat, agg, fc


@st.fragment(run_every="1h")
def _weekly_auto_refresh():
    """Heartbeat so an idle, always-on server refreshes at the Monday 00:00 rollover with no
    visitor: hourly it checks the ISO week and, on change, clears the cache and reruns the
    whole app, which re-pulls Socrata and rewrites the fallback snapshot."""
    wk = date.today().strftime("%G-W%V")
    prev = st.session_state.get("analysis_week")
    st.session_state["analysis_week"] = wk
    if prev is not None and prev != wk:
        run_analysis.clear()
        st.rerun(scope="app")


# --------------------------------------------------------------------------- #
def main():
    st.set_page_config(page_title="LAPD Resource Allocation Advisor",
                       page_icon="🛡️", layout="wide")
    _inject_css()

    # --- Header (text only; no emblem/logo by design) ---
    st.markdown("###### LOS ANGELES POLICE DEPARTMENT")
    st.markdown("## Resource Allocation Advisor")
    st.markdown("<hr>", unsafe_allow_html=True)

    # --- Sidebar ---
    st.sidebar.header("Analysis settings")
    # Default = 2 years (seasonality); stepped in 10-day increments.
    days = st.sidebar.slider("Analysis window (days)", 90, 760, LOOKBACK_DAYS, step=10)
    if st.sidebar.button("🔄 Refresh data", width="stretch"):
        run_analysis.clear()
    st.sidebar.caption("Auto-refreshes every Monday 00:00; Refresh forces an immediate pull.")

    # ISO week (Monday-anchored) drives the automatic weekly refresh.
    iso_week = date.today().strftime("%G-W%V")
    _weekly_auto_refresh()

    # --- Phase 1: automated analysis ---
    try:
        with st.spinner("Loading and analyzing calls for service…"):
            raw, cat, agg, fc = run_analysis(days, iso_week)
    except Exception as e:  # EH-5
        st.error(f"Analysis could not be completed: {e}")
        st.stop()

    if len(raw) == 0:
        st.warning("No calls returned for this window (live source and sample both empty). "
                   "Try a wider window or check connectivity.")
        st.stop()

    st.sidebar.caption(f"Data source: {raw.attrs.get('source', 'unknown')}")
    st.sidebar.caption(f"Window: last {days} days · {len(raw):,} calls")

    crime = cat[cat["category"] != PROACTIVE]
    priority = analyze.area_priority(fc)

    tab_overview, tab_trends, tab_alloc = st.tabs(
        ["📊 Overview", "📈 Crime trends", "🚔 Resource allocation"])

    # ===================== OVERVIEW =====================
    with tab_overview:
        total_calls = int(cat["n"].sum())
        crime_calls = int(crime["n"].sum())
        violent_calls = int(crime.loc[crime["category"] == VIOLENT, "n"].sum())
        violent_share = 100 * violent_calls / max(crime_calls, 1)
        proactive_calls = int(cat.loc[cat["category"] == PROACTIVE, "n"].sum())

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Calls (window)", f"{total_calls:,}")
        k2.metric("Reported crime", f"{crime_calls:,}",
                  help="Citizen-reported calls; excludes officer-initiated CODE 6 activity.")
        k3.metric("Violent-crime share", f"{violent_share:.1f}%")
        k4.metric("Highest-priority area",
                  priority.iloc[0]["area_occ"] if len(priority) else "—")

        st.caption(f"Proactive (CODE 6) activity excluded from priority: "
                   f"{proactive_calls:,} calls · Forecast horizon: next ISO week.")

        left, right = st.columns(2)
        with left:
            st.altair_chart(
                _hbar(priority.head(12), "priority_index", "area_occ",
                      "Priority index (0–100)", "Area", "Area priority (relative, 100 = top)"),
                width="stretch")
        with right:
            st.altair_chart(_hbar(_category_mix(crime), "calls", "category",
                                  "Calls", "Category", "Citizen-reported call mix"),
                            width="stretch")

    # ===================== CRIME TRENDS =====================
    with tab_trends:
        areas = ["All areas"] + sorted(cat["area_occ"].unique())
        area = st.selectbox("Area", areas)
        if area == "All areas":
            trend, label = analyze.weekly_totals(agg), "all areas"
            mix = _category_mix(crime)
        else:
            trend = analyze.weekly_incidence(area, agg)
            label = area
            mix = _category_mix(crime[crime["area_occ"] == area])
        c1, c2 = st.columns([3, 2])
        with c1:
            st.altair_chart(_line(trend.sort_values("iso_week"),
                                  f"Weekly calls — {label}"), width="stretch")
        with c2:
            if len(mix):
                st.altair_chart(_hbar(mix, "calls", "category", "Calls", "Category",
                                      f"Category mix — {label}"), width="stretch")
        st.subheader("Next-week forecast by area & category")
        st.dataframe(
            fc.sort_values("forecast_incidence", ascending=False)
              .rename(columns={"forecast_incidence": "forecast (next wk)"}),
            width="stretch", hide_index=True)

    # ===================== RESOURCE ALLOCATION =====================
    with tab_alloc:
        st.caption("‘Deployable patrol units’ is a department-supplied operational figure for "
                   "this watch (not in the dataset). It scales the unit counts; the area ranking "
                   "is unchanged by it.")
        # Confirm with EITHER the Enter key in the field OR the button -- both MUST use the number
        # currently in the field. A number_input inside an st.form does NOT reliably commit the
        # typed value when Enter is pressed (Enter submits the form before the field commits/blurs),
        # so Enter fell back to the TOTAL_PATROL_UNITS default (300). Fix: drop the form and use a
        # keyed number_input whose on_change callback fires on Enter AND on blur, plus a button whose
        # on_click runs the SAME callback -- so the keyboard and mouse paths are identical.
        def _confirm_units():
            st.session_state["confirmed_units"] = int(st.session_state["alloc_units"])

        st.number_input("Deployable patrol units this watch", 50, 5000,
                        TOTAL_PATROL_UNITS, step=10, key="alloc_units",
                        on_change=_confirm_units)
        st.button("✅ Confirm units & generate allocation", width="stretch",
                  on_click=_confirm_units)

        if "confirmed_units" in st.session_state:
            u = st.session_state["confirmed_units"]
            plan = suggest.allocate(fc, u)
            db.set_cache(db.current_week_key(), plan)
            st.success(f"Allocation generated for {u:,} confirmed deployable units.")

            c1, c2 = st.columns([2, 3])
            with c1:
                st.altair_chart(
                    _hbar(plan, "recommended_units", "area_occ", "Units", "Area",
                          "Recommended units by area"),
                    width="stretch")
            with c2:
                st.dataframe(plan, width="stretch", hide_index=True)

            st.subheader("Weekly deployment plan")
            st.markdown(suggest.narrative(plan))
            st.download_button("⬇ Download plan (CSV)", plan.to_csv(index=False),
                               "weekly_plan.csv", "text/csv")
        else:
            st.info("Confirm the deployable patrol units above to generate the allocation "
                    "and the written deployment plan.")


if __name__ == "__main__":
    main()
