# LAPD Resource Allocation Advisor

Streamlit app. Ingests LAPD Calls for Service (Socrata `xjgu-z4ju`, trailing 2 years), categorizes by
crime taxonomy + severity, forecasts next-week load per area, and allocates a patrol-unit pool by
severity-weighted priority. AI narrative via Google Gemini behind a single swappable adapter
(`suggest.generate_text`). Runs offline (last-good snapshot, then bundled sample) and with no API key (template narrative).

## Rebuild (AI agent)
Read `docs/00`–`docs/06` in full, then execute `docs/00`. It writes every file from `docs/04` verbatim,
runs the gate (`pytest -q` + `python verify.py` → `ALL CHECKS PASSED`), and on Windows runs `install.ps1`
(Desktop icon + login auto-start + persistent server). Docs:

| Doc | Content |
|-----|---------|
| `docs/00` | build procedure |
| `docs/01` | functional spec |
| `docs/02` | architecture, schemas, taxonomy, formulas |
| `docs/03` | algorithm + layout |
| `docs/04` | verbatim file contents (authoritative) |
| `docs/05` | standards + threat model |
| `docs/06` | persistent deployment |

## Run
- Windows (one-time install): `powershell -ExecutionPolicy Bypass -File install.ps1`.
- Then open the app any time — even with the AI agent gone — via **any** of: the Desktop/Start Menu
  icon "LAPD Resource Advisor", `Start_LAPD_Advisor.cmd` in this folder, or `pythonw launch.py`. The
  icon targets the venv's `pythonw.exe` running `launch.py`, so it opens the app **windowless — no
  PowerShell/VBScript and no console** (those are blocked or removed on modern Windows). It starts the
  server if needed, reuses it if already up, and opens the browser; it also auto-starts silently at
  login. `Start_LAPD_Advisor.cmd` additionally rebuilds `.venv` if it was deleted or the folder copied.
  See `docs/06 §6.0` for why the user path uses `pythonw launch.py`, not the agent-only `run_app.ps1`.
- Cross-platform: `python -m venv .venv` → `pip install -r requirements.txt` → `streamlit run app/app.py`.

App runs without an API key (template narrative) and without network (sample CSV). Server binds
`127.0.0.1`. Optional `GEMINI_API_KEY` in `.env` enriches the prose.

## Data
Socrata `xjgu-z4ju` (LAPD Calls for Service 2024–Present), updated weekly. The app analyzes a trailing
**2-year** window (to span seasonal cycles), excludes the current in-progress ISO week, and auto-refreshes
at the **Monday 00:00** ISO-week rollover (manual Refresh also available). Each successful pull is cached to
`data/last_good_calls.csv` and used as the offline fallback before the bundled sample.
Fields: `incident_number`, `area_occ`, `rpt_dist`, `dispatch_date`, `dispatch_time`, `call_type_code`, `call_type_text`.
