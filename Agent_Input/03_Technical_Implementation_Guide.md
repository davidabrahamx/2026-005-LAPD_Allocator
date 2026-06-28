# 3. Implementation Guide

`docs/04` is authoritative for file bytes. This is the algorithm + layout. Code MUST also satisfy `docs/05`.

## 3.0 Stack
Python 3.10+, Streamlit, pandas, numpy, requests, `google-genai`, sqlite3 (stdlib), python-dotenv.

`requirements.txt`:
```
streamlit>=1.58
altair>=5.0
pandas>=2.2
numpy>=2.0
requests>=2.32
google-genai>=1.0
python-dotenv>=1.0
```
(`streamlit>=1.58` for `width="stretch"`; `altair` imported directly so declared.)

**Version-sensitive (use these forms):**
- pandas 3.x: `pd.read_json` needs a file-like object — wrap JSON strings in `io.StringIO(...)`.
- Python 3.12+: use `datetime.now(timezone.utc)`, not `datetime.utcnow()`.
- google-genai 1.x/2.x: `genai.Client(api_key=...).models.generate_content(model=..., contents=..., config=types.GenerateContentConfig(system_instruction=..., temperature=...))`. The pre-1.0 `genai.configure()`/`GenerativeModel()` API is obsolete.

### Layout
```
LAPD-Resource-Advisor/
├── app/{__init__,config,db,ingest,categorize,analyze,suggest,app}.py
├── data/sample_calls.csv
├── tests/{__init__,test_pipeline}.py
├── .streamlit/config.toml
├── docs/                  # 00–06
├── .env.example  .gitignore  .dockerignore
├── verify.py  requirements.txt
├── Dockerfile  docker-compose.yml
├── run_app.ps1  run_app.sh        # AGENT/build-time persistent start (job-object escape; Win / *nix)
├── install.ps1                    # Win one-time setup: venv+deps + 3 user entry points
├── launch.py                      # USER entry point: pythonw runs it windowless (no console/VBScript)
├── Start_LAPD_Advisor.cmd         # Win fallback: bootstraps venv if missing, then pythonw launch.py
└── README.md
```
Exact file list + order: manifest at top of `docs/04`.

## 3.1 config.py
All tunables. `load_dotenv()`. `GEMINI_API_KEY=env("",)`, `GEMINI_MODEL=env("gemini-3.5-flash")`,
`DATASET_ID="xjgu-z4ju"`, `SODA_ENDPOINT=f".../resource/{DATASET_ID}.json"`, `LOOKBACK_DAYS=730` (2y),
`TOTAL_PATROL_UNITS=300`, `DB_PATH`, `SAMPLE_CSV`, `LAST_GOOD_CSV` (rolling fallback snapshot). Define `SEVERITY_WEIGHTS` and ordered
`CATEGORY_RULES` exactly per `docs/02 §2.5`; `DEFAULT_CATEGORY=OTHER`. Header is text-only (no seal
config / no image). `configure_logging()` = `logging.basicConfig(level=LOG_LEVEL)`.

## 3.2 db.py — SQLite result cache, key = ISO week
```
init_db():        CREATE TABLE IF NOT EXISTS cache(key TEXT PK, payload TEXT, created_at TEXT)
get_cache(key):   row = SELECT payload WHERE key=?; return pd.read_json(io.StringIO(row)) or None
set_cache(key,df):INSERT OR REPLACE (key, df.to_json(), datetime.now(timezone.utc).isoformat())
current_week_key(prefix="plan"): f"{prefix}:{date.today():%G-W%V}"
```
Best-effort: any sqlite error logged at WARNING and swallowed (cache miss / no-op).

## 3.3 ingest.py — Socrata SODA + rolling-snapshot/CSV fallback
Aggregate server-side over a 2-YEAR window (seasonality). Output `NORMALIZED_COLUMNS`. Every successful
pull rewrites `LAST_GOOD_CSV`; failures fall back to that snapshot, then the bundled sample. `_finish`
drops the current in-progress ISO week.
```
load_calls(days=LOOKBACK_DAYS):                       # LOOKBACK_DAYS=730
  days = clamp(int(days),1,800)                      # IV-1 (admit 2-year window)
  cutoff = (today - days).isoformat()
  params = {$select: "area_occ, call_type_code, call_type_text,
            date_extract_y(dispatch_date) AS yr, date_extract_woy(dispatch_date) AS wk, count(1) AS n",
            $where: f"dispatch_date >= '{cutoff}'", $group: "area_occ,call_type_code,call_type_text,yr,wk",
            $limit: 500000}                            # 2y aggregate >> 90-day
  try:  GET SODA_ENDPOINT (timeout=60); raise_for_status; df=DataFrame(json); assert not empty
        df = from_aggregated(df); _save_last_good(df)  # iso_week=f"{yr}-W{wk:02d}", n=int; refresh snapshot
  except network|empty:  df,source = _load_fallback(cutoff)   # LAST_GOOD_CSV (normalized) else SAMPLE_CSV (n=1)
  return normalized df                                # never raises (EH-2)
_save_last_good(df):    df.to_csv(LAST_GOOD_CSV)       # best-effort; logged on error
_load_fallback(cutoff): LAST_GOOD_CSV if exists -> _finish(snap); else _from_raw(read_csv(SAMPLE_CSV) filtered)
_finish(df):            normalize cols; drop iso_week == today's ISO week (in-progress); -> NORMALIZED_COLUMNS
```
No auth (public). `cutoff` is server-derived (T2: no free-text user value in query).

## 3.4 categorize.py — rule-based, deterministic (no AI)
```
classify_row(text,code): haystack=f"{text} {code}"; first rule whose any(token in haystack) wins → (cat, SEVERITY_WEIGHTS[cat]); else (OTHER, weight)
categorize(df): classify the DISTINCT (text,code) pairs, merge back onto rows (left)
```

## 3.5 analyze.py
Series span ~104 ISO weeks (2-year window), in-progress week already removed in ingest. `forecast`
applies a linear trend × multiplicative **week-of-year** seasonal index (ratio-to-trend), so recurring
holiday weeks shift the prediction; with <1 full year the factor defaults to 1.0 (pure trend).
```
aggregate(df): df.sev_n=severity*n; groupby(area,category,iso_week).agg(incidence=Σn, magnitude=Σsev_n)
_week_of_year("YYYY-Www") -> int wk
_next_week_of_year(last):  date.fromisocalendar(yr,wk,1)+7d -> .isocalendar().week   # next week's woy (rolls year)
_seasonal_index(y,trend_fit,woy): ratios=y/trend_fit (trend_fit>0); factor[woy]=mean(ratios); normalize mean→1; {} if trend≤0
forecast(agg): per (area,cat) sorted by week; y=incidence; k=len(y)
   if k≥3: slope,intercept=polyfit(arange(k),y,1); trend_next=slope*k+intercept
           season=_seasonal_index(y, slope*arange(k)+intercept, woy)
           yhat=max(0, trend_next * season.get(_next_week_of_year(weeks[-1]), 1.0)); trend by slope
   else:   yhat=mean(y) or 0; trend=flat
   row: forecast_incidence=round(yhat,1), trend, severity=SEVERITY_WEIGHTS[cat]
area_priority(fc): priority=forecast_incidence*severity; by_area=Σ; top_category per area;
               priority_index=round(100*priority/max,1); rank=1..N. cols: area_occ,priority_index,top_category,rank
```

## 3.6 suggest.py
```
allocate(fc, total_units=TOTAL_PATROL_UNITS):
  total_units=max(0,int(total_units))                # IV-2
  by_area = area_priority(fc); recommended_units = largest_remainder(priority_index, total_units)
  return [rank, area_occ, top_category, priority_index, recommended_units]
largest_remainder(weights,total): floor quotas, hand leftover units to largest fractions; Σ==total, rank preserved
generate_text(system,prompt):                        # ONLY Gemini-aware code
  if not GEMINI_API_KEY: raise; genai.Client(...).models.generate_content(model, contents=prompt,
    config=types.GenerateContentConfig(system_instruction=system, temperature=0.3)) → resp.text
narrative(plan): system="police analyst; concise, non-discriminatory; AREA level only; never individuals";
  prompt=table JSON + "3-5 bullets (area, top category, units) + 1 data-limitation caveat";
  try generate_text else _template_narrative(plan)
```

## 3.7 app.py — Streamlit UI
Text-only header (no emblem/logo/seal — do NOT add an image fetch). 3 tabs. Altair charts (titled,
labeled). PROACTIVE excluded from citizen-reported KPIs and call-mix. Use `width="stretch"`.
```
@st.cache_data run_analysis(days, iso_week): raw=load_calls; cat=categorize; agg=aggregate; fc=forecast → (raw,cat,agg,fc)
#   iso_week is cache-key only: rolls over Mon 00:00 -> automatic weekly refresh
@st.fragment(run_every="1h") _weekly_auto_refresh(): if ISO week changed -> run_analysis.clear(); st.rerun(scope="app")
main():
  set_page_config(page_icon="🛡️", layout="wide"); inject_css(); text header
  days = sidebar.slider(90,760,LOOKBACK_DAYS,step=10); Refresh → run_analysis.clear(); caption("auto Mon 00:00")
  iso_week = today %G-W%V; _weekly_auto_refresh()
  try raw,cat,agg,fc = run_analysis(days, iso_week) except: st.error; st.stop()   # EH-5
  if len(raw)==0: st.warning; st.stop()
  crime = cat[cat.category != PROACTIVE]; priority = area_priority(fc)
  Overview: KPIs (calls, reported crime, violent share, top area) + 2 Altair bars
  Trends:   area selectbox; weekly line + category mix; forecast table
  Allocation (gated): keyed number_input(units 50..5000 default 300, key="alloc_units",
                      on_change=confirm) + button(on_click=confirm); confirm() sets
                      confirmed_units from session_state["alloc_units"]. Do NOT use st.form here:
                      inside a form, pressing Enter does not reliably commit the typed value and
                      falls back to the 300 default — Enter MUST behave identically to the button.
                      On confirm: allocate; db.set_cache; bars + table + narrative + download CSV; else st.info
```

## 3.9 Env & run
`.env.example`: `GEMINI_API_KEY=` / `GEMINI_MODEL=gemini-3.5-flash`. Run: `streamlit run app/app.py`.

## 3.10 Acceptance
- [ ] Launches with `streamlit run app/app.py`.
- [ ] Phase 1 auto-renders; Phase 2 appears only after confirming units (default 300).
- [ ] No network → loads sample CSV; no key → template narrative; neither crashes.
- [ ] Every row has category ∈ taxonomy, severity ∈ {0..5} (0 only PROACTIVE, excluded from priority).
- [ ] `recommended_units` are non-negative ints summing to the pool; table sorted by priority_index desc, rank 1..N.
- [ ] Same ISO week re-run reads SQLite cache.
- [ ] Window = 2 years (`LOOKBACK_DAYS=730`); the current in-progress ISO week is excluded from the series.
- [ ] A successful pull rewrites `data/last_good_calls.csv`; offline uses it before the bundled sample.
- [ ] Auto-refreshes at the Monday 00:00 ISO-week rollover; manual Refresh still forces a pull.
- [ ] Forecast applies a multiplicative week-of-year seasonal factor (holiday-aware); degrades to trend-only (factor 1.0) when <1 year of data, so the sample gate output is unchanged.
