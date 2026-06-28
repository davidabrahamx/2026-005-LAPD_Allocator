# 2. Architecture & Contracts

Single-process Streamlit app. Linear pipeline + one swappable AI adapter + local SQLite cache.

Data flow:
`ingest → categorize → analyze(aggregate→forecast→area_priority) → suggest(allocate→narrative) → UI`
Source: Socrata `xjgu-z4ju` (live HTTP) with `data/sample_calls.csv` fallback. AI: Gemini via
`google-genai`, with template fallback. Cache: SQLite (`db.py`).

## 2.1 Components
| Layer | Tech | Responsibility |
|-------|------|----------------|
| UI | Streamlit + Altair | Tabs: Overview / Crime trends / Resource allocation. Text-only header (no emblem). Phase 1 (KPIs, charts, forecast) auto-renders; Phase 2 (allocation + narrative) gated on confirmed units |
| Pipeline | pandas, numpy | ingest → categorize → analyze → suggest |
| Persistence | sqlite3 | cache raw pulls + weekly results |
| AI adapter | google-genai | metrics → written plan |
| External data | Socrata SODA | LAPD calls |
| Config | `.env` + `config.py` | keys, dataset id, lookback, taxonomy, weights, pool |

## 2.2 Module contract
| Module | Public fn | In | Out |
|--------|-----------|----|----|
| `config.py` | constants | — | settings, `CATEGORY_RULES`, `SEVERITY_WEIGHTS`, `TOTAL_PATROL_UNITS` |
| `ingest.py` | `load_calls(days=730)` | days | raw calls DF (`NORMALIZED_COLUMNS`) |
| `categorize.py` | `categorize(df)` | raw | + `category`, `severity` |
| `analyze.py` | `aggregate`, `forecast`, `area_priority`, `weekly_incidence`, `weekly_totals` | categorized | aggregates; forecast; ranking |
| `suggest.py` | `allocate(fc, units)`, `narrative(plan)` | forecast | allocation table; plan text |
| `db.py` | `get_cache`/`set_cache`/`current_week_key` | key | cached DF or None |
| `app.py` | `main()` | — | Streamlit UI |

Dependencies (no cycles): `app → {ingest,categorize,analyze,suggest,db,config}`; `suggest → {gemini,config}`; all → `config`.

## 2.3 Control flow
1. Analysis is cached per `(days, ISO-week)`; the ISO-week key rolls over Monday 00:00, so a new week auto-refreshes. Manual "Refresh data" clears the cache for an immediate pull.
2. `ingest.load_calls(730)`: try Socrata (server-side 2-year weekly aggregate); on success rewrite the rolling fallback snapshot (`last_good_calls.csv`); on error use that snapshot, else the bundled sample CSV. The in-progress ISO week is dropped.
3. `categorize`: per distinct (text,code), first-matching `CATEGORY_RULES` wins → attach category + severity.
4. `aggregate`: group (area,category,iso_week) → incidence=Σn, magnitude=Σ(severity×n).
5. `forecast`: per (area,category), linear trend × week-of-year seasonal index over ~104 weeks → forecast_incidence (clamp ≥0).
6. Phase 1 renders automatically. Phase 2: planner confirms units (default 300) → `allocate` → `db.set_cache` → `narrative` (Gemini or template).

## 2.4 Schemas (stage contracts)
**A — raw (ingest).** Live query aggregates server-side to weekly grain; CSV path yields same shape with n=1.
| col | type | meaning |
|-----|------|---------|
| `area_occ` | str | LAPD area |
| `call_type_code` | str | raw code |
| `call_type_text` | str | raw text |
| `iso_week` | str | `YYYY-Www` |
| `n` | int | count in (area, call type, week) |

**B — categorized.** A + `category` (enum §2.5), `severity` (int 0–5; 0 only for PROACTIVE).
**C — aggregate.** `area_occ, category, iso_week, incidence` (Σn, int), `magnitude` (Σ severity×n, int).
**D — forecast.** Grain (area_occ, category) + `forecast_incidence` (float ≥0), `trend` (`up`/`flat`/`down`), `severity`.
**E — allocation.** `area_occ, priority_index` (float 0–100; 100=top), `recommended_units` (int), `top_category` (str), `rank` (int, 1=highest).

## 2.5 Taxonomy & severity (ordered; FIRST MATCH WINS)
Tokens are uppercased substrings matched against `call_type_text + " " + call_type_code`. Must match `config.py` exactly.

| # | Category | Severity | Tokens |
|:-:|----------|:--------:|--------|
| 1 | `PROACTIVE` | 0 | `CODE 6`, `BACK-UP`, `990` |
| 2 | `VIOLENT` | 5 | `187`,`211`,`245`,`242`,`243`,`246`,`261`,`207`,`209`,`422`,`417`,`ADW`,`ROBBERY`,`BATTERY`,`SHOTS`,`SHOOTING`,`STABBING`,`RAPE`,`KIDNAP`,`CRIMINAL THREATS`,`WEAPON`,`GUN`,`KNIFE` |
| 3 | `DOMESTIC` | 4 | `DOM VIOL`,`273.5`,`CHILD ABUSE`,`SPOUSE`,`620 FAMILY`,`FAMILY`,`DOMESTIC` |
| 4 | `PROPERTY` | 3 | `459`,`484`,`487`,`488`,`594`,`10851`,`503`,`BURGLARY`,`THEFT`,`STOLEN`,`GTA`,`VANDAL`,`SHOPLIFT`,`PROWLER` |
| 5 | `VICE_NARCOTICS` | 3 | `314`,`288`,`647B`,`11350`,`11377`,`NARCO`,`DRUGS`,`PROSTITUT`,`INDECENT`,`LEWD` |
| 6 | `MEDICAL_WELFARE` | 1 | `AMB`,`O/D`,`OVERDOSE`,`SUICIDE`,`MENTAL`,`5150`,`918`,`WELFARE`,`PERSON DOWN`,`SICK`,`INJURED`,`D/B`,`DEAD BODY` |
| 7 | `TRAFFIC` | 2 | `TRAFFIC`,`T/C`,`DUI`,`COLLISION`,`23152`,`20002`,`HIT AND RUN`,`HIT/RUN`,`H & R`,`H&R` |
| 8 | `ALARM` | 1 | `906`,`RINGER`,`ALARM`,`CODE 30` |
| 9 | `DISTURBANCE` | 2 | `415`,`507`,`921`,`620`,`390`,`DISTURB`,`PARTY`,`NOISE`,`TRESPASS`,`PROWL`,`LOUD`,`NEIGHBOR`,`DRINK`,`DRUNK`,`647` |
| – | `OTHER` | 1 | default (no match) |

Precedence is load-bearing: violence codes (242/245) outrank DOMESTIC context, so `242 DOM VIOL` → VIOLENT while `620 FAMILY` → DOMESTIC and generic `620` → DISTURBANCE. PROACTIVE (weight 0) is shown for context but excluded from magnitude/priority. Editable in `config.py`.

## 2.6 Forecast model
Per (area, category) weekly `incidence` over the last ~104 ISO weeks (two full years), EXCLUDING the
current in-progress week. Model = linear trend × multiplicative **week-of-year** seasonal index
(ratio-to-trend decomposition), so recurring holiday weeks adjust the forecast (e.g. Jul-4 ≈ W27,
Thanksgiving ≈ W47-48, Christmas/New-Year ≈ W52/W01):
```
slope,intercept = polyfit(arange(k), y, 1)          # k = #observed weeks (≥3)
trend_next      = slope*k + intercept               # deseasonalized level for next week
season[woy]     = mean( y / (slope*x+intercept) ) over weeks sharing that ISO week-of-year, mean→1
forecast        = max(0, trend_next * season.get(next_week_of_year, 1.0))   # 1.0 if woy unseen (<1y)
```
clamp ≥0; if <3 weeks use mean. `trend`: `up` if slope>+0.5, `down` if <−0.5, else `flat`.

## 2.7 Allocation model
```
priority(area,cat)      = forecast_incidence × severity_weight
priority(area)          = Σ_cat priority(area,cat)
recommended_units(area) = largest_remainder(TOTAL_PATROL_UNITS × priority(area) / Σ priority)
```
`TOTAL_PATROL_UNITS` is an operational input (default ~300), set in UI. Allocation is proportional so it
only scales output; ranking/split are invariant. Hamilton/largest-remainder apportionment makes
Σ recommended_units == pool exactly and never inverts rank order.

## 2.8 AI adapter boundary
`suggest.narrative(plan)` → `generate_text(system, prompt)`. Only `generate_text` knows Gemini; swapping
providers = swap that one function. No key / call fails → deterministic template from the same table.

## 2.9 Fallback matrix
| Failure | Detection | Fallback |
|---------|-----------|----------|
| Socrata unreachable | HTTP error/timeout | last good snapshot `data/last_good_calls.csv`, else `data/sample_calls.csv` |
| Empty 2-year result | `len(df)==0` | last snapshot / sample / warn |
| No AI key or AI error | env/exception | template narrative |
| Stale cache | week-key mismatch | recompute |

## 2.10 Non-functional
Reproducible; offline-capable; single command; pure-Python; SQLite file in project dir.
