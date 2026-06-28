"""Deterministic allocation + AI narrative (docs/03 STEP 6).

The ONLY Gemini-aware code is `generate_text`. Swap that one function to target
Anthropic or OpenAI; everything else is provider-agnostic.
"""
import logging

import pandas as pd

from app import analyze
from app.config import GEMINI_API_KEY, GEMINI_MODEL, TOTAL_PATROL_UNITS

logger = logging.getLogger(__name__)


# --- 6a. Deterministic allocation -------------------------------------------
def allocate(fc: pd.DataFrame, total_units: int = TOTAL_PATROL_UNITS) -> pd.DataFrame:
    """Apportion `total_units` across areas by severity-weighted forecast priority.

    Builds on the shared `analyze.area_priority` ranking, then apportions the
    integer unit pool by the largest-remainder method.
    """
    total_units = max(0, int(total_units))  # IV-2: positive int; guards divide-by-zero
    by_area = analyze.area_priority(fc)
    cols = ["rank", "area_occ", "top_category", "priority_index", "recommended_units"]
    if by_area.empty:
        by_area["recommended_units"] = pd.Series(dtype=int)
        return by_area[cols]
    by_area["recommended_units"] = _largest_remainder(
        by_area["priority_index"], total_units)
    return by_area[cols]


def _largest_remainder(weights: pd.Series, total_units: int) -> pd.Series:
    """Apportion `total_units` integers proportional to `weights` (Hamilton method).

    Guarantees the result sums exactly to `total_units` and never gives a
    higher-weighted area fewer units than a lower-weighted one.
    """
    total_w = weights.sum()
    if total_w <= 0:
        return pd.Series([0] * len(weights), index=weights.index)
    quota = total_units * weights / total_w
    floors = quota.apply(int)
    remainder = int(total_units - floors.sum())
    # hand out the leftover units to the largest fractional parts
    fractions = (quota - floors).sort_values(ascending=False)
    for idx in fractions.index[:remainder]:
        floors.at[idx] += 1
    return floors.astype(int)


# --- 6b. AI adapter boundary -------------------------------------------------
def generate_text(system: str, prompt: str) -> str:
    """Provider seam. Only this function knows about Gemini."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set")
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)
    resp = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.3,
        ),
    )
    return resp.text


def narrative(plan_df: pd.DataFrame) -> str:
    system = (
        "You are a police resource-deployment analyst. Be concise, factual, and "
        "non-discriminatory. Recommend only at the AREA level; never target "
        "individuals or demographics."
    )
    prompt = (
        "Given this ranked weekly allocation table (JSON):\n"
        + plan_df.to_json(orient="records")
        + "\n\nWrite a weekly deployment plan: 3-5 bullet priorities. Each bullet names "
        "the area, its top crime category, and the recommended unit count. End with one "
        "short caveat about data limitations (calls-for-service != confirmed crime)."
    )
    try:
        return generate_text(system, prompt)
    except Exception as e:
        logger.warning("Gemini narrative failed (%s); using deterministic template", e)
        return _template_narrative(plan_df)


def _template_narrative(plan_df: pd.DataFrame) -> str:
    """Deterministic fallback used when no AI key / AI call fails."""
    lines = ["**Weekly deployment plan (template — no AI key configured):**", ""]
    for _, r in plan_df.head(5).iterrows():
        lines.append(
            f"- **{r['area_occ']}** (rank {r['rank']}): focus **{r['top_category']}**; "
            f"deploy **{r['recommended_units']}** units "
            f"(priority index {r['priority_index']}/100)."
        )
    lines += ["",
              "_Caveat: figures are derived from LAPD calls for service, which reflect "
              "reported activity and dispatch volume, not confirmed crimes._"]
    return "\n".join(lines)
