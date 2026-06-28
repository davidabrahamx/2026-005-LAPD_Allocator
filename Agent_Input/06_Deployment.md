# 6. Deployment (persistent, independent of the agent)

## 6.0 Two SEPARATE problems — do not conflate them
This is the crux. The app is a local web server; "the user starts the program" means: ensure the
server is running, then open the browser. Two distinct lifetimes are involved:

- **P1 — agent build-time start.** An AI agent's spawned processes go into a Windows Job Object
  marked kill-on-close; when the agent exits, that job is destroyed, killing any
  `Start-Process`/`pythonw`/headless server it launched. To bring the app up DURING the build and
  have it outlive the agent, the server must be started from a parent OUTSIDE the agent's job.
  `run_app.ps1` does this (Task Scheduler, else WMI `Win32_Process.Create`); `run_app.sh` uses
  `setsid`. **This is the ONLY thing run_app.ps1 is for.**

- **P2 — user "start it anytime later" (the important one).** When the human double-clicks the icon
  weeks later, that process runs in Explorer's context, which is NOT a kill-on-close job, so the
  server it starts survives. The user path must use NEITHER the P1 escape machinery (Task Scheduler /
  WMI) NOR any Windows scripting engine (VBScript/`wscript.exe`, PowerShell): all of those are
  blocked, constrained, or being removed on modern/managed Windows and fail silently. Instead the
  shortcut targets the venv's **`pythonw.exe`** (GUI-subsystem Python = no console) running
  **`launch.py`**, which reuses a running server or starts one detached, then opens the browser.

Rule: **build-time uses `run_app.ps1`; the user double-clicks an icon that runs `pythonw launch.py`.**
Both are idempotent (health check first) and both log to `streamlit.log` (+ `streamlit.log.err`).

### Why `pythonw.exe launch.py` (and not a .ps1/.vbs/.cmd shortcut)
A double-click must work on a normal, locked-down machine with no agent present and no console
flashing. The constraints rule the field down to one robust choice:
- **VBScript** (`wscript.exe`) is deprecated and shipping as a removable Windows feature; ASR rules
  and SmartScreen actively block it. Not dependable.
- **PowerShell** as a shortcut target flashes a `conhost` window and is the #1 target of execution
  policy / Constrained Language Mode / ASR lockdowns.
- **A .cmd** always opens a console window.
- **`pythonw.exe`** is a normal GUI-subsystem executable (it ships inside the venv we just built).
  Running it shows NO console, uses NO scripting engine, and is not what script-blocking rules target.
  It is the most broadly allowed console-free launch without shipping a compiled binary.
`launch.py` therefore: probes/binds the literal **`127.0.0.1`** (not `localhost`, which can resolve to
IPv6 `::1` first and be refused — the old "waits forever" bug); **health-checks before starting** so a
second click never stacks a second server; starts Streamlit **detached + windowless** (so it outlives
the launcher); waits for health; opens the browser; and on failure shows a native message box (the only
UI a windowless process has) instead of failing silently.

## 6.A Windows installer + three user entry points (recommended)
```
powershell -ExecutionPolicy Bypass -File install.ps1
```
Creates venv + deps (and a `.venv\.deps_installed` sentinel), then exposes `launch.py` THREE
independent ways so at least one always works after the agent is gone — none of them uses VBScript,
PowerShell, or a console window:
1. **Desktop + Start Menu shortcut** "LAPD Resource Advisor" → target `…\.venv\Scripts\pythonw.exe`,
   argument `launch.py`. Windowless; the browser opens when ready; a pop-up reports any error.
2. **`Start_LAPD_Advisor.cmd`** in the app folder → fallback if the `.lnk` is policy-blocked. It first
   **bootstraps** the venv (only if missing — e.g. the folder was copied to a new PC), then hands off
   to `pythonw.exe launch.py` and closes. The only path that may briefly show a window, and only on
   first-run setup.
3. **Startup-folder shortcut** → `pythonw.exe launch.py --quiet` at every login (silent). This is the
   SOLE login auto-start: `run_app.ps1`'s build-time task is registered without a logon trigger, so the
   two never both fire at logon and stack duplicate servers.

install.ps1 also performs the P1 build-time start via `run_app.ps1` so the app is reachable
immediately and the install can be verified. Pin to taskbar = manual (right-click → Pin). Custom
icon: drop `assets/app.ico` before install. Folder moved or `.venv` deleted? `Start_LAPD_Advisor.cmd`
rebuilds the environment on the next start.

## 6.B Docker (optional, server "deploy and forget")
```
docker compose up -d --build   # http://localhost:8501; restart: unless-stopped
docker compose logs -f
docker compose down
```
Secrets via shell/`.env`: `GEMINI_API_KEY`, `GEMINI_MODEL`. Container binds 0.0.0.0 (Dockerfile CLI flags);
put behind agency access controls (§6.D).

## 6.C Persistent local process (no Docker)
```
# Windows
powershell -ExecutionPolicy Bypass -File run_app.ps1
# macOS/Linux
./run_app.sh
```
Windows: starts outside the agent's job (Task Scheduler or WMI, §6.0); logs `streamlit.log`. Stop:
```
Stop-ScheduledTask -TaskName 'LAPD-Resource-Advisor' 2>$null; Unregister-ScheduledTask -TaskName 'LAPD-Resource-Advisor' -Confirm:$false 2>$null
Get-CimInstance Win32_Process | ? { $_.CommandLine -like '*streamlit*app/app.py*' } | % { Stop-Process -Id $_.ProcessId -Force }
```
*nix: `setsid`+`nohup`; logs `streamlit.log`; stop `pkill -f 'streamlit run app/app.py'`.

## 6.D Settings & security
`.streamlit/config.toml`: `headless=true`, `port=8501`, `address=127.0.0.1` (loopback only — no firewall
prompt, not LAN/internet-reachable; matches "no auth" posture), `fileWatcherType=none`, stats off, minimal
toolbar. Docker overrides to `0.0.0.0` via CLI flags + adds `/_stcore/health` check. No built-in auth: do
not expose publicly; for any networked deploy use a reverse proxy / VPN with TLS + authentication.

## 6.E Hosted (fully independent)
Streamlit Community Cloud (point at `app/app.py`, set `GEMINI_API_KEY` secret) or any VM/server running
Docker behind a TLS reverse proxy / as a service.
