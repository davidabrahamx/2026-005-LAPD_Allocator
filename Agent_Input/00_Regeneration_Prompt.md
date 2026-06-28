# 0. Build Instructions (AI agent)

Execute this document. It rebuilds and launches the app from the blueprint in this folder.
Do not improvise, rename, add, or "improve" anything.

## Inputs (read ALL before writing code)

| Doc | Role | Precedence |
|-----|------|-----------|
| `docs/00` | this file: procedure | — |
| `docs/01` | functional spec (what the app must do) | INTENT |
| `docs/02` | architecture, per-stage schemas, taxonomy/severity table | CONTRACTS |
| `docs/03` | algorithm + layout, step by step | METHOD |
| `docs/04` | verbatim contents of every file | FILE BYTES (authoritative) |
| `docs/05` | mandatory standards + threat model | REQUIREMENTS |
| `docs/06` | persistent run / process lifecycle | DEPLOY |

Conflict resolution: file contents → `04`; behavior → `01`/`02`; `03` explains. They do not actually conflict.

## Procedure (in order; stop and report on any failure)

0. Read `docs/00`–`docs/06` in full. Then write a 2–3 sentence confirmation naming what each covers.
1. Create folders: `app/`, `data/`, `tests/`, `.streamlit/`. (`docs/` exists; other paths are created in step 2.)
2. For each `### File: <path>` block in `docs/04`, create `<path>` and write the fenced content EXACTLY — byte for byte, ASCII only, no edits. Use the manifest order at the top of `docs/04`.
3. Create venv and install with the venv Python directly (do not rely on shell activation):
   ```
   python -m venv .venv
   # Windows:
   .venv\Scripts\python -m pip install --upgrade pip
   .venv\Scripts\python -m pip install -r requirements.txt
   # macOS/Linux:
   .venv/bin/python -m pip install --upgrade pip
   .venv/bin/python -m pip install -r requirements.txt
   ```
4. GATE — run both with the venv Python; both must pass:
   ```
   .venv\Scripts\python -m pytest -q      # (or .venv/bin/python) — all tests pass
   .venv\Scripts\python verify.py         # must print "ALL CHECKS PASSED", exit 0
   ```
   On failure: (a) diff the file on disk vs its `docs/04` block; if different, re-copy verbatim and rerun the gate ONCE. (b) If they match or the rerun still fails, STOP and report full output. Do not loop.
5. After both pass, install/launch persistently (server must outlive this session). Do not require Docker.
   ```
   # Windows (primary): venv reuse + deps + Desktop & Start Menu icon + login auto-start + start server.
   powershell -ExecutionPolicy Bypass -File install.ps1
   # macOS/Linux: start persistent server (no desktop installer on these platforms).
   bash run_app.sh
   # Optional, only if Docker present:
   docker compose up -d --build
   ```
   These return immediately. Do not re-run them. Poll health (cold start ≤ ~2 min):
   ```
   # Windows:
   1..60 | % { try { if((Invoke-WebRequest -UseBasicParsing http://localhost:8501/_stcore/health).StatusCode -eq 200){"UP";break} } catch { Start-Sleep 3 } }
   # macOS/Linux:
   for i in $(seq 60); do curl -sf http://localhost:8501/_stcore/health && break || sleep 3; done
   ```
   On no-200, read `streamlit.log` (next to the app) for the cause. Report `http://localhost:8501`.
6. VERIFY THE USER CAN START IT LATER (this is the deliverable, not just a running server). On Windows confirm ALL of these exist AND that the Desktop shortcut targets pythonw.exe (windowless; NO PowerShell/VBScript on the user path — those are blocked or removed on modern Windows):
   - Desktop shortcut `LAPD Resource Advisor.lnk` whose TargetPath ends in `pythonw.exe`
   - `launch.py` in the app folder
   - `Start_LAPD_Advisor.cmd` in the app folder
   ```
   $d = [Environment]::GetFolderPath("Desktop")
   foreach ($p in @(".\launch.py", ".\Start_LAPD_Advisor.cmd")) {
       if (Test-Path $p) { "OK  $p" } else { "MISSING  $p" }
   }
   $lnk = (New-Object -ComObject WScript.Shell).CreateShortcut("$d\LAPD Resource Advisor.lnk")
   if ($lnk.TargetPath -match 'pythonw\.exe$') { "OK  shortcut -> $($lnk.TargetPath)" } else { "BAD shortcut target: $($lnk.TargetPath)" }
   ```
   Any `MISSING`/`BAD` → re-run `install.ps1` and report. Do NOT hand off until all are `OK`.

## Constraints
- Use only the deps in `requirements.txt`. Add nothing.
- Must run with NO network and NO API key (Socrata→`data/sample_calls.csv`, Gemini→template narrative).
- Never commit secrets. `.env` is the user's to fill, not yours.

## Done
- `pytest -q` all pass AND `verify.py` prints `ALL CHECKS PASSED`.
- `http://localhost:8501/_stcore/health` returns 200 from a background process independent of this session.
- Windows: the operator can start the app with NO agent present, via ANY of these (all created by `install.ps1`): the Desktop/Start Menu shortcut "LAPD Resource Advisor" (targets `pythonw.exe launch.py` — windowless, no VBScript/PowerShell), `Start_LAPD_Advisor.cmd` in the app folder, or `pythonw launch.py`. `launch.py` reuses a running server or starts one detached and self-heals deps; `Start_LAPD_Advisor.cmd` additionally rebuilds the `.venv` if it was deleted or the folder was copied. See `docs/06 §6.0` for why the user path uses `pythonw launch.py`, not the agent-only `run_app.ps1`.

## Expected gate output (deterministic, from `data/sample_calls.csv`, 300-unit pool)
```
 rank  area_occ   top_category  priority_index  recommended_units
    1   Central        VIOLENT           100.0                102
    2 Southeast        VIOLENT            70.9                 73
    3 Hollywood VICE_NARCOTICS            56.0                 57
    4  Van Nuys       PROPERTY            40.3                 41
    5    Newton        VIOLENT            26.1                 27
ALL CHECKS PASSED
```
`recommended_units` sum to 300. The live app analyzes all areas from Socrata; this fixture exercises the pipeline on 5 sample areas.
