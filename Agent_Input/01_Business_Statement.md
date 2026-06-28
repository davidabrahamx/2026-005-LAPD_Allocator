# 1. Functional Spec — LAPD Resource Allocation Advisor

## What it does
Weekly decision-support tool. Ingests the trailing 2 years of LAPD Calls for Service (Socrata
`xjgu-z4ju`), produces a ranked per-area patrol-allocation plan with an AI-written narrative.

Pipeline (4 stages):
1. **Categorize** — map each raw call type (radio + penal codes, e.g. `211`, `459`, `415 FAMILY`)
   to a taxonomy (VIOLENT, DOMESTIC, PROPERTY, VICE_NARCOTICS, DISTURBANCE, TRAFFIC, ALARM,
   MEDICAL_WELFARE, PROACTIVE, OTHER) with a severity weight. PROACTIVE = officer-initiated `CODE 6`
   (~46% of calls), weight 0, excluded from priority.
2. **Analyze** — aggregate by (area, category, ISO week): `incidence` = call count,
   `magnitude` = severity-weighted count.
3. **Forecast** — per (area, category), linear trend × multiplicative week-of-year seasonal index
   over the ~104-week (2-year) window, so recurring holiday weeks adjust the prediction (in-progress
   week excluded) → next-week `forecast_incidence`.
4. **Suggest** — after the planner confirms deployable patrol units (default 300), allocate the pool
   proportional to `forecast_incidence × severity_weight`; render the table as prose via Gemini.

Output: ranked area table + AI narrative (where, why, how much to shift).

## Properties
- Deterministic pipeline; only narrative wording varies by AI.
- Runs offline (last-good snapshot, then bundled sample) and with no API key (template narrative).
- Single command: `streamlit run app/app.py`.

## Scope
In: descriptive analytics, lightweight trend forecasting, allocation recommendation over public
Calls-for-Service data.
Out (by design): no targeting of individuals; no PII/arrest/disposition data; recommendations only
(never automated dispatch); forecasts are directional aids.

## Success criteria
| Metric | Target |
|--------|--------|
| Plan from one run | < 2 min, one command |
| Data freshness | last 2 years; auto-refresh Mon 00:00 + manual; weekly Socrata source |
| Reproducibility | identical inputs → identical ranking |
| Transparency | every category/weight/score inspectable in UI |
| Resilience | runs offline (sample) and with no AI key (template) |

## Users
Watch commanders/planners (consume plan); analysts (inspect/tune weights); command/oversight
(review rationale). Primary use: "Each Monday, generate next week's recommended patrol distribution
across areas, ranked by forecasted severity-weighted load, with written justification."
