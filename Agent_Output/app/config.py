"""Central configuration: all tunables live here (see docs/03 STEP 1).

Nothing else in the app should hard-code a dataset id, weight, or threshold.
"""
import logging
import os

from dotenv import load_dotenv

load_dotenv()

# --- Logging (see docs/05 §5.2). Entry points call configure_logging() once. ---
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")


def configure_logging() -> None:
    """Configure root logging once (idempotent). Called by app.py and verify.py."""
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

# --- AI provider (Gemini today; swap only suggest.generate_text for others) ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# Current stable Flash tier. Alternatives via the GEMINI_MODEL env var:
#   gemini-flash-latest  -> auto-tracks the newest Flash (changes with ~2-week notice)
#   gemini-3.5-flash     -> same model, pinned version name
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

# --- Data source: LAPD Calls for Service 2024-Present (Socrata SODA) ---
DATASET_ID = "xjgu-z4ju"
SODA_ENDPOINT = f"https://data.lacity.org/resource/{DATASET_ID}.json"
# Two full years (~104 ISO weeks) so the forecast's week-of-year seasonal index sees each
# holiday week in >=2 years and can adjust for it. The current in-progress ISO week is dropped
# in ingest._finish so a partial week never skews the fit; ingest.load_calls lifts its day cap.
LOOKBACK_DAYS = 730  # "last 2 years" (seasonality-aware)

# --- Allocation ---
# Deployable patrol units to distribute across the 21 LAPD areas for the planning
# watch. This is an OPERATIONAL INPUT the department sets each week (it varies with
# overtime, leave, and events) and is NOT in the public dataset. ~300 is a realistic
# watch-level placeholder; the allocation is proportional, so this value only scales
# the output — it does not change the area ranking. Override it in the UI per run.
TOTAL_PATROL_UNITS = 300

# --- Local paths ---
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
DB_PATH = os.path.join(_ROOT, "lapd_cache.sqlite")
# Bundled, version-controlled cold-start sample (raw one-row-per-incident).
SAMPLE_CSV = os.path.join(_ROOT, "data", "sample_calls.csv")
# Rolling snapshot of the most recent SUCCESSFUL live pull (already normalized). Rewritten on
# every successful refresh and used as the offline fallback BEFORE SAMPLE_CSV, so the fallback
# always reflects the last good data (see ingest.load_calls).
LAST_GOOD_CSV = os.path.join(_ROOT, "data", "last_good_calls.csv")

# --- Crime taxonomy ---
# Categories are derived from the LAPD Calls-for-Service vocabulary, which mixes
# radio codes (e.g. "415", "620", "906", "CODE 6") with penal codes and plain text.
VIOLENT = "VIOLENT"
DOMESTIC = "DOMESTIC"
PROPERTY = "PROPERTY"
VICE_NARCOTICS = "VICE_NARCOTICS"
DISTURBANCE = "DISTURBANCE"
TRAFFIC = "TRAFFIC"
ALARM = "ALARM"
MEDICAL_WELFARE = "MEDICAL_WELFARE"
PROACTIVE = "PROACTIVE"  # CODE 6: officer-initiated field investigation, not a crime report
OTHER = "OTHER"

# Severity drives both `magnitude` and the allocation priority (see analyze.area_priority).
# PROACTIVE has weight 0 by design: it is shown for context but EXCLUDED from the
# resource-allocation priority (it is officer activity, not citizen-reported crime).
SEVERITY_WEIGHTS = {
    VIOLENT: 5,
    DOMESTIC: 4,
    PROPERTY: 3,
    VICE_NARCOTICS: 3,
    DISTURBANCE: 2,
    TRAFFIC: 2,
    ALARM: 1,
    MEDICAL_WELFARE: 1,
    PROACTIVE: 0,
    OTHER: 1,
}

# Ordered rules; FIRST MATCH WINS. Tokens are matched as uppercased substrings against
# (call_type_text + " " + call_type_code). Order encodes precedence: an actual violence
# code (242/245) outranks the "domestic" context, a real crime outranks a medical assist,
# and officer-initiated CODE 6 is captured before anything else.
CATEGORY_RULES = [
    # Officer-initiated activity (largest single value ~46%); not a citizen crime call.
    (PROACTIVE, ["CODE 6", "BACK-UP", "990"]),
    # Violent / weapons / threats.
    (VIOLENT, ["187", "211", "245", "242", "243", "246", "261", "207", "209",
               "422", "417", "ADW", "ROBBERY", "BATTERY", "SHOTS", "SHOOTING",
               "STABBING", "RAPE", "KIDNAP", "CRIMINAL THREATS", "WEAPON",
               "GUN", "KNIFE"]),
    # Domestic / family violence and disputes (penal 273.5; radio 620 + family text).
    (DOMESTIC, ["DOM VIOL", "273.5", "CHILD ABUSE", "SPOUSE", "620 FAMILY",
                "FAMILY", "DOMESTIC"]),
    # Property crime.
    (PROPERTY, ["459", "484", "487", "488", "594", "10851", "503", "BURGLARY",
                "THEFT", "STOLEN", "GTA", "VANDAL", "SHOPLIFT", "PROWLER"]),
    # Vice / narcotics / sex offenses (288 = lewd acts w/ child).
    (VICE_NARCOTICS, ["314", "288", "647B", "11350", "11377", "NARCO", "DRUGS",
                      "PROSTITUT", "INDECENT", "LEWD"]),
    # Medical / mental-health / welfare assists.
    (MEDICAL_WELFARE, ["AMB", "O/D", "OVERDOSE", "SUICIDE", "MENTAL", "5150",
                       "918", "WELFARE", "PERSON DOWN", "SICK", "INJURED",
                       "D/B", "DEAD BODY"]),
    # Traffic.
    (TRAFFIC, ["TRAFFIC", "T/C", "DUI", "COLLISION", "23152", "20002",
               "HIT AND RUN", "HIT/RUN", "H & R", "H&R"]),
    # Alarms.
    (ALARM, ["906", "RINGER", "ALARM", "CODE 30"]),
    # Disturbances / quality-of-life / non-family disputes (incl. generic 620).
    (DISTURBANCE, ["415", "507", "921", "620", "390", "DISTURB", "PARTY", "NOISE",
                   "TRESPASS", "PROWL", "LOUD", "NEIGHBOR", "DRINK", "DRUNK", "647"]),
]
DEFAULT_CATEGORY = OTHER

SOURCE_COLUMNS = [
    "incident_number", "area_occ", "rpt_dist", "dispatch_date",
    "dispatch_time", "call_type_code", "call_type_text",
]

# Internal normalized shape (after ingest): one row per (area, call type, ISO week)
# with a count `n`. This lets the live query aggregate server-side and still cover the
# full window without hitting the row cap.
NORMALIZED_COLUMNS = ["area_occ", "call_type_code", "call_type_text", "iso_week", "n"]

# --- Branding ---
# The header is intentionally TEXT-ONLY (no emblem/logo/seal image). Official seals are
# protected insignia, and a generated placeholder looks off — so the UI shows a clean typeset
# title instead. This also keeps the app fully offline (no image fetch at startup).
