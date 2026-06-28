"""Rule-based crime categorization (docs/03 STEP 4). Deterministic, no AI."""
import pandas as pd

from app.config import (CATEGORY_RULES, DEFAULT_CATEGORY, SEVERITY_WEIGHTS)


def classify_row(text: str, code: str):
    """Return (category, severity). First matching rule wins."""
    haystack = f"{text} {code}"
    for category, tokens in CATEGORY_RULES:
        if any(token in haystack for token in tokens):
            return category, SEVERITY_WEIGHTS[category]
    return DEFAULT_CATEGORY, SEVERITY_WEIGHTS[DEFAULT_CATEGORY]


def categorize(df: pd.DataFrame) -> pd.DataFrame:
    """Attach category + severity. Classifies only the DISTINCT (text, code) pairs
    (hundreds) and merges back, instead of running the rules on every row (tens of
    thousands) — the call-type vocabulary is small, so this is a large speedup.
    """
    df = df.copy()
    keys = df[["call_type_text", "call_type_code"]].drop_duplicates()
    classed = keys.apply(
        lambda r: classify_row(r["call_type_text"], r["call_type_code"]),
        axis=1, result_type="expand",
    )
    keys = keys.assign(category=classed[0], severity=classed[1].astype(int))
    return df.merge(keys, on=["call_type_text", "call_type_code"], how="left")
