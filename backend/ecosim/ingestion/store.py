"""Write canonical tidy frames to the partitioned Parquet store.

Layout: ``timeseries/scenario=<s>/domain=<d>/variable=<v>/freq=<f>/part.parquet``.
Each dataset is one file so re-ingesting a scenario only rewrites its slices.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ecosim.core.schema import TIMESERIES_ARROW_SCHEMA, TIMESERIES_COLUMNS


def _coerce(df: pd.DataFrame) -> pd.DataFrame:
    df = df.reindex(columns=TIMESERIES_COLUMNS).copy()
    for col in ("year", "month", "group_id", "fleet_id", "partner_id"):
        df[col] = df[col].astype("Int32")
    df["value"] = pd.to_numeric(df["value"], errors="coerce").astype("float64")
    for col in ("model", "model_name", "scenario", "domain", "variable", "freq", "date",
                "group_name", "fleet_name", "partner_name", "unit", "run_id"):
        df[col] = df[col].astype("string")
    return df


def write_dataset(df: pd.DataFrame, timeseries_dir: Path) -> Path:
    """Write a single (scenario, domain, variable, freq) slice; return its path."""
    if df.empty:
        raise ValueError("Refusing to write an empty dataset")
    df = _coerce(df)
    scenario = df["scenario"].iloc[0]
    domain = df["domain"].iloc[0]
    variable = df["variable"].iloc[0]
    freq = df["freq"].iloc[0]
    out_dir = (
        timeseries_dir
        / f"scenario={scenario}" / f"domain={domain}"
        / f"variable={variable}" / f"freq={freq}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(df, schema=TIMESERIES_ARROW_SCHEMA, preserve_index=False)
    out_path = out_dir / "part.parquet"
    pq.write_table(table, out_path)
    return out_path
