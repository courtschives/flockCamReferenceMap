"""Helpers for county/state FIPS mapping.

This module expects a county FIPS lookup CSV to be available if needed.
Provide a `data/counties.csv` file with columns: state_fips, county_fips, state, county.
"""
import pandas as pd
from pathlib import Path

def load_county_lookup(csv_path=None):
    if csv_path is None:
        # look for data/counties.csv in repo
        repo_root = Path(__file__).resolve().parents[2]
        csv_path = repo_root / 'data' / 'counties.csv'
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f'County lookup CSV not found at {csv_path}')
    df = pd.read_csv(csv_path, dtype=str)
    return df
