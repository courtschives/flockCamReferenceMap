"""Fetch Census ACS variables and normalize to county FIPS.

This module fetches ACS5 county-level variables, joins them to the TIGER
county geometries (downloaded by `tiger_counties.download_and_prepare`) and
writes both a CSV and a GeoJSON county file with a `county_fips` key suitable
for downstream tile generation.

Usage example:
  python -m data_pipeline.pipelines.census_acs --vars B01003_001E --out data/output/census_counties.geojson
"""
import requests
import pandas as pd
from pathlib import Path
from time import sleep
from ..utils.credentials import get_credential
from ..utils.tiger_counties import download_and_prepare
import geopandas as gpd

CENSUS_API_URL = 'https://api.census.gov/data/2024/acs/acs5'

# Race/ethnicity breakdown as % of county total population (B01003_001E).
# B02001 is the Census race table (mutually exclusive "alone" categories);
# B03003_003E (Hispanic or Latino) comes from the separate Hispanic-origin
# table, since Census treats Hispanic/Latino as an ethnicity orthogonal to
# race - a person counted there may also be counted in any B02001 category.
RACE_GROUP_VARS = {
    'pct_white': 'B02001_002E',
    'pct_black': 'B02001_003E',
    'pct_aian': 'B02001_004E',
    'pct_asian': 'B02001_005E',
    'pct_nhpi': 'B02001_006E',
    'pct_two_or_more': 'B02001_008E',
    'pct_hispanic': 'B03003_003E',
}


def add_race_percentages(gdf):
    """Add pct_* columns (share of B01003_001E) for whichever RACE_GROUP_VARS
    source columns are present. No-op for columns that weren't fetched."""
    if 'B01003_001E' not in gdf.columns:
        return gdf
    total = pd.to_numeric(gdf['B01003_001E'], errors='coerce')
    for pct_col, source_col in RACE_GROUP_VARS.items():
        if source_col in gdf.columns:
            count = pd.to_numeric(gdf[source_col], errors='coerce')
            gdf[pct_col] = (count / total * 100).where(total > 0)
    return gdf


def fetch_county_vars(vars_list, key, year=2024, retries=3):
    # `state` and `county` are provided by the `for=county:*` clause and
    # should not be included in the `get` parameter as variables. Request
    # the requested variables plus `NAME` for readability; the API will
    # still return `state` and `county` columns because of the `for`.
    params = {'get': ','.join(vars_list + ['NAME']), 'for': 'county:*', 'key': key}
    headers = {'User-Agent': 'FlockMap/1.0', 'Accept': 'application/json'}
    last_exc = None
    for attempt in range(retries):
        try:
            resp = requests.get(CENSUS_API_URL, params=params, headers=headers, timeout=60)
            resp.raise_for_status()
            # Guard against empty bodies or non-JSON responses
            if not resp.text or resp.text.strip() == '':
                raise ValueError('Empty response body from Census API')
            data = resp.json()
            df = pd.DataFrame(data[1:], columns=data[0])
            return df
        except Exception as exc:
            last_exc = exc
            sleep(2 ** attempt)
            continue
    # If we reach here, re-raise the last exception with context
    raise RuntimeError(f'Failed to fetch Census variables after {retries} attempts') from last_exc


def normalize_county_geodata(df, tiger_geojson_path=None):
    """Join ACS table `df` with TIGER counties and return a GeoDataFrame.

    The returned GeoDataFrame will have `county_fips` as string and all ACS
    variables preserved as columns.
    """
    repo_root = Path(__file__).resolve().parents[2]
    if tiger_geojson_path is None:
        tiger_geojson_path = repo_root / 'data' / 'tiger_counties.geojson'
    if not Path(tiger_geojson_path).exists():
        download_and_prepare(output_path=tiger_geojson_path)
    counties = gpd.read_file(str(tiger_geojson_path)).to_crs(epsg=4326)
    # Ensure county_fips column
    if 'GEOID' in counties.columns:
        counties['county_fips'] = counties['GEOID'].astype(str)
    else:
        counties['county_fips'] = counties['STATEFP'].astype(str).str.zfill(2) + counties['COUNTYFP'].astype(str).str.zfill(3)

    # Prepare ACS df: build GEOID
    df = df.copy()
    df['county_fips'] = df['state'].astype(str).str.zfill(2) + df['county'].astype(str).str.zfill(3)
    # drop 'state'/'county' raw columns
    df = df.drop(columns=['state', 'county'], errors='ignore')
    # convert numeric-looking columns to numeric where possible
    for col in df.columns:
        if col == 'county_fips':
            continue
        df[col] = pd.to_numeric(df[col], errors='ignore')

    # merge
    merged = counties.merge(df, left_on='county_fips', right_on='county_fips', how='left')
    return merged


def run(vars_list, out_path, tiger_geojson_path=None):
    key = get_credential('CENSUS_API_KEY')
    if not key:
        raise RuntimeError('Census API key not found in credentials.txt')
    try:
        df = fetch_county_vars(vars_list, key)
        gdf = normalize_county_geodata(df, tiger_geojson_path=tiger_geojson_path)
    except Exception as exc:
        # Fallback: produce a county GeoDataFrame with the requested variable
        # present but null. This keeps downstream tooling working when the
        # Census API is temporarily unavailable.
        print(f'Warning: Census fetch failed ({type(exc).__name__}: {exc}). Producing empty county file with null variables as fallback.')
        repo_root = Path(__file__).resolve().parents[2]
        if tiger_geojson_path is None:
            tiger_geojson_path = repo_root / 'data' / 'tiger_counties.geojson'
        if not Path(tiger_geojson_path).exists():
            download_and_prepare(output_path=tiger_geojson_path)
        gdf = gpd.read_file(str(tiger_geojson_path)).to_crs(epsg=4326)
        if 'GEOID' in gdf.columns:
            gdf['county_fips'] = gdf['GEOID'].astype(str)
        else:
            gdf['county_fips'] = gdf['STATEFP'].astype(str).str.zfill(2) + gdf['COUNTYFP'].astype(str).str.zfill(3)
        # Add requested variables as nulls
        for v in vars_list:
            gdf[v] = pd.NA
    gdf = add_race_percentages(gdf)

    outp = Path(out_path)
    outp.parent.mkdir(parents=True, exist_ok=True)
    # write GeoJSON
    gdf.to_file(str(outp), driver='GeoJSON')
    # also write CSV for quick inspection
    csv_out = outp.with_suffix('.csv')
    gdf.drop(columns='geometry').to_csv(str(csv_out), index=False)
    print(f'Wrote {len(gdf)} county features to {outp} and CSV to {csv_out}')


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--vars', required=True, help='comma-separated variable codes (e.g. B01003_001E)')
    p.add_argument('--out', required=True, help='output GeoJSON path')
    p.add_argument('--tiger', help='optional path to tiger_counties.geojson')
    args = p.parse_args()
    vars_list = [v.strip() for v in args.vars.split(',') if v.strip()]
    run(vars_list, args.out, tiger_geojson_path=args.tiger)
