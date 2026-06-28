# 5. Mandatory Standards & Threat Model

Requirements. The code in `docs/04` already satisfies these. Gate: `pytest -q` + `verify.py` (§5.7).

## 5.1 Error handling
- EH-1: No stage crashes the app on bad external data; every outbound dep (Socrata, Gemini, SQLite) has a fallback (§2.9).
- EH-2: `ingest.load_calls` falls back to sample CSV on any network/HTTP/parse error, then to an empty normalized DataFrame — never raises to UI.
- EH-3: cache (`db.get_cache`/`set_cache`) best-effort: any SQLite error logged + swallowed.
- EH-4: Gemini call best-effort: any failure → template narrative.
- EH-5: `app.py` wraps the pipeline in try/except → `st.error` + `st.stop` (no raw traceback); zero rows → `st.warning` + stop.
- EH-6: No bare `except:`; use `except Exception as e:` and log `e`.

## 5.2 Logging
- LOG-1: every module `logger = logging.getLogger(__name__)`; no `print()` in library code.
- LOG-2: entry points (`app.py`, `verify.py`) call `config.configure_logging()` once (`basicConfig`, level from `LOG_LEVEL`, default INFO).
- LOG-3: fallback paths log WARNING with cause; total failures ERROR.
- LOG-4: never log secrets (API key, tokenized URLs, raw PII).

## 5.3 Secrets & config
- SEC-1: Gemini key only from env (`.env` via python-dotenv); never hard-coded/committed/rendered/logged.
- SEC-2: `.gitignore` excludes `.env`, `*.sqlite`, `__pycache__/`, `.venv/`, `.streamlit/secrets.toml`. Only `.env.example` committed.
- SEC-3: all tunables (endpoints, weights, model id, pool) in `config.py`/env.

## 5.4 Threat model
| # | Threat | Mitigation |
|---|--------|-----------|
| T1 | Secret leakage | SEC-1/2; env only; gitignore; never logged |
| T2 | SoQL injection | only query input is `days` → coerced int + clamped; cutoff server-derived; no free-text in query |
| T3 | Prompt injection / exfiltration | only aggregated controlled-vocab values (areas, labels, ints) sent to Gemini; system prompt constrains scope; output advisory only |
| T4 | PII exposure | dataset is public, no PII; app must not add PII/identities/address-level; only aggregates cached |
| T5 | Biased recommendations | taxonomy/weights explicit + editable; PROACTIVE excluded from priority; area-level only; recommendation not dispatch; caveat in UI |
| T6 | Stale model/dep | model id + versions configurable (`GEMINI_MODEL`, §3.0 notes) |
| T7 | Upstream abuse/outage | server-side `$limit`, request timeout, CSV fallback |

No authentication (single-operator/trusted use). Bind loopback; never expose publicly; deploy behind agency access controls.

## 5.5 Input validation
- IV-1: `days` → int, clamped 1..800 before query (admits the 2-year window).
- IV-2: `total_units` → non-negative int; non-positive → zero allocation (no crash/divide-by-zero).
- IV-3: normalization guarantees source columns exist + coerced, regardless of source.

## 5.6 Docs & style
- DOC-1: each module has a top docstring (role + docs/03 step).
- DOC-2: each public fn has docstring + type hints.
- DOC-3: non-obvious decisions get a why-comment (Hamilton, StringIO/read_json, precedence).
- DOC-4: descriptive names; no single-letter except loop/comprehension indices.

## 5.7 Testing (gate)
- TST-1: `verify.py` = deterministic offline integration gate; prints `ALL CHECKS PASSED`, exit 0.
- TST-2: `tests/test_pipeline.py` (pytest) covers ≥: categorization precedence (`242 DOM VIOL`→VIOLENT; `620 FAMILY`→DOMESTIC; `CODE 6`→PROACTIVE sev 0); allocation invariants (units sum to pool; rank never inverts); normalization produces all columns.
- TST-3: both `pytest -q` and `python verify.py` pass before the build is correct.

## 5.8 Compliance checklist
- [ ] No bare `except:`; fallbacks logged with cause.
- [ ] `logging` throughout; entry points call `configure_logging()`.
- [ ] `.gitignore` excludes `.env`, `*.sqlite`, caches; key env-only.
- [ ] `days` and `total_units` validated/clamped.
- [ ] No PII ingested/stored; only aggregates to Gemini.
- [ ] Severity/taxonomy explicit; PROACTIVE excluded from priority.
- [ ] Every module + public fn documented and type-hinted.
- [ ] `pytest -q` and `python verify.py` pass.
