"""FBI Crime Data Explorer (CDE) pipeline: hate crime + general offense rate.

Two sub-layers, deliberately built at DIFFERENT geographic resolutions because
of a real API constraint discovered while probing it (not a design choice):

  - Hate crime rate: the CDE `/hate-crime/agency/{ori}` endpoint returns real,
    agency-specific data (verified: NYPD's numbers are a genuine subset of New
    York's state numbers, not identical to them). This is aggregated up to
    county level via the ORI -> county-name crosswalk from `/agency/byStateAbbr`,
    for a curated set of counties (top-N by population + every state capital's
    county) rather than all ~18,000 agencies nationwide, which would mean tens
    of thousands of API calls.

  - General offense rate ("rate per offense"): the CDE `/summarized/agency/{ori}/...`
    endpoint is effectively broken at agency granularity - verified live: NYPD's
    "agency-level" response is byte-for-byte identical to New York's state-level
    response, and the same substitution happens for a tiny rural agency too. This
    isn't a small-agency fallback quirk, it's systematic. So this sub-layer is
    built at STATE level only (`/summarized/state/{abbr}/{offense}`) and applied
    uniformly to every county in that state - full nationwide coverage, honestly
    labeled as state-level rather than faking county precision the API can't back up.

Counties outside the hate-crime target list get null (not zero) for that
sub-layer - the client must treat null as "no data for this county," not "no
hate crime here."
"""
import sys
import time
import json
from pathlib import Path

import pandas as pd
import geopandas as gpd
import requests

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from data_pipeline.utils.credentials import get_credential

CDE_BASE = 'https://api.usa.gov/crime/fbi/cde'
REQUEST_DELAY_SECONDS = 0.8  # observed 403s at rapid-fire; this rate ran clean during probing
DATE_FROM = '01-2022'
DATE_TO = '12-2023'

# Every state capital's county, by county NAME as it appears in Census/TIGER
# data (independent cities are their own "county-equivalent" - Carson City,
# Richmond city - handled the same way as any other county name here).
STATE_CAPITAL_COUNTIES = {
    'AL': 'Montgomery County', 'AK': 'Juneau City and Borough', 'AZ': 'Maricopa County',
    'AR': 'Pulaski County', 'CA': 'Sacramento County', 'CO': 'Denver County',
    'CT': 'Hartford County', 'DE': 'Kent County', 'FL': 'Leon County',
    'GA': 'Fulton County', 'HI': 'Honolulu County', 'ID': 'Ada County',
    'IL': 'Sangamon County', 'IN': 'Marion County', 'IA': 'Polk County',
    'KS': 'Shawnee County', 'KY': 'Franklin County', 'LA': 'East Baton Rouge Parish',
    'ME': 'Kennebec County', 'MD': 'Anne Arundel County', 'MA': 'Suffolk County',
    'MI': 'Ingham County', 'MN': 'Ramsey County', 'MS': 'Hinds County',
    'MO': 'Cole County', 'MT': 'Lewis and Clark County', 'NE': 'Lancaster County',
    'NV': 'Carson City', 'NH': 'Merrimack County', 'NJ': 'Mercer County',
    'NM': 'Santa Fe County', 'NY': 'Albany County', 'NC': 'Wake County',
    'ND': 'Burleigh County', 'OH': 'Franklin County', 'OK': 'Oklahoma County',
    'OR': 'Marion County', 'PA': 'Dauphin County', 'RI': 'Providence County',
    'SC': 'Richland County', 'SD': 'Hughes County', 'TN': 'Davidson County',
    'TX': 'Travis County', 'UT': 'Salt Lake County', 'VT': 'Washington County',
    'VA': 'Richmond city', 'WA': 'Thurston County', 'WV': 'Kanawha County',
    'WI': 'Dane County', 'WY': 'Laramie County',
}

OFFENSE_CATEGORIES = {
    'violent-crime': 'offense_rate_violent',
    'property-crime': 'offense_rate_property',
    'homicide': 'offense_rate_homicide',
    'robbery': 'offense_rate_robbery',
    'burglary': 'offense_rate_burglary',
    'motor-vehicle-theft': 'offense_rate_mvtheft',
}

BIAS_CATEGORY_TO_COL = {
    'Race/Ethnicity/Ancestry': 'hate_crime_race',
    'Religion': 'hate_crime_religion',
    'Sexual Orientation': 'hate_crime_orientation',
    'Gender Identity': 'hate_crime_gender_identity',
    'Disability': 'hate_crime_disability',
    'Gender': 'hate_crime_gender',
}

US_STATE_ABBR = {
    'Alabama': 'AL', 'Alaska': 'AK', 'Arizona': 'AZ', 'Arkansas': 'AR', 'California': 'CA',
    'Colorado': 'CO', 'Connecticut': 'CT', 'Delaware': 'DE', 'Florida': 'FL', 'Georgia': 'GA',
    'Hawaii': 'HI', 'Idaho': 'ID', 'Illinois': 'IL', 'Indiana': 'IN', 'Iowa': 'IA',
    'Kansas': 'KS', 'Kentucky': 'KY', 'Louisiana': 'LA', 'Maine': 'ME', 'Maryland': 'MD',
    'Massachusetts': 'MA', 'Michigan': 'MI', 'Minnesota': 'MN', 'Mississippi': 'MS',
    'Missouri': 'MO', 'Montana': 'MT', 'Nebraska': 'NE', 'Nevada': 'NV',
    'New Hampshire': 'NH', 'New Jersey': 'NJ', 'New Mexico': 'NM', 'New York': 'NY',
    'North Carolina': 'NC', 'North Dakota': 'ND', 'Ohio': 'OH', 'Oklahoma': 'OK',
    'Oregon': 'OR', 'Pennsylvania': 'PA', 'Rhode Island': 'RI', 'South Carolina': 'SC',
    'South Dakota': 'SD', 'Tennessee': 'TN', 'Texas': 'TX', 'Utah': 'UT', 'Vermont': 'VT',
    'Virginia': 'VA', 'Washington': 'WA', 'West Virginia': 'WV', 'Wisconsin': 'WI',
    'Wyoming': 'WY', 'District of Columbia': 'DC',
}


def _normalize_county_name(name):
    if not name:
        return ''
    n = name.upper().strip()
    for suffix in [' COUNTY', ' PARISH', ' CITY AND BOROUGH', ' BOROUGH', ' CITY']:
        if n.endswith(suffix):
            n = n[:-len(suffix)]
    return n.strip()


def _get(url, params, retries=5):
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in (403, 429):
                wait = 3 * (attempt + 1)
                print(f'  Rate limited ({resp.status_code}), backing off {wait}s...')
                time.sleep(wait)
                continue
            print(f'  HTTP {resp.status_code} for {url}')
            return None
        except requests.RequestException as exc:
            print(f'  Request error: {exc}, retrying...')
            time.sleep(2 * (attempt + 1))
    return None


def pick_target_counties(census_csv, top_n, tiger_geojson_path):
    df = pd.read_csv(census_csv, dtype={'county_fips': str})
    df = df.sort_values('B01003_001E', ascending=False)
    top = df.head(top_n).copy()

    counties_gdf = gpd.read_file(str(tiger_geojson_path))
    if 'GEOID' in counties_gdf.columns:
        counties_gdf['county_fips'] = counties_gdf['GEOID'].astype(str)
    name_col = 'NAME' if 'NAME' in counties_gdf.columns else 'NAMELSAD'
    state_col = 'STATE_NAME' if 'STATE_NAME' in counties_gdf.columns else None

    capital_fips = []
    missing_capitals = []
    for abbr, county_name in STATE_CAPITAL_COUNTIES.items():
        norm_target = _normalize_county_name(county_name)
        match = counties_gdf[counties_gdf[name_col].apply(lambda n: _normalize_county_name(n) == norm_target)]
        if state_col:
            state_full = [k for k, v in US_STATE_ABBR.items() if v == abbr]
            if state_full:
                match = match[match[state_col] == state_full[0]]
        if len(match) >= 1:
            capital_fips.append(match.iloc[0]['county_fips'])
        else:
            missing_capitals.append((abbr, county_name))

    if missing_capitals:
        print(f'Warning: could not match {len(missing_capitals)} state capitals to a county: {missing_capitals}')

    target_fips = set(top['county_fips'].astype(str)) | set(capital_fips)
    print(f'Target counties: {len(top)} by population + {len(capital_fips)} capitals -> {len(target_fips)} unique')
    return target_fips


def fetch_agency_directory(state_abbr):
    data = _get(f'{CDE_BASE}/agency/byStateAbbr/{state_abbr}', {'api_key': API_KEY})
    time.sleep(REQUEST_DELAY_SECONDS)
    if not data:
        return []
    agencies = []
    for county_key, agency_list in data.items():
        for a in agency_list:
            agencies.append(a)
    return agencies


def fetch_hate_crime_for_ori(ori):
    data = _get(f'{CDE_BASE}/hate-crime/agency/{ori}', {'from': DATE_FROM, 'to': DATE_TO, 'api_key': API_KEY})
    time.sleep(REQUEST_DELAY_SECONDS)
    if not data:
        return None
    return data.get('incident_section', {}).get('bias_category', {})


def fetch_state_offense_rate(state_abbr, offense):
    data = _get(f'{CDE_BASE}/summarized/state/{state_abbr}/{offense}',
                {'from': DATE_FROM, 'to': DATE_TO, 'api_key': API_KEY})
    time.sleep(REQUEST_DELAY_SECONDS)
    if not data:
        return None
    rates = data.get('offenses', {}).get('rates', {})
    series = None
    for key, values in rates.items():
        if key.endswith('Offenses') and not key.startswith('United States'):
            series = values
            break
    if not series:
        return None
    vals = [v for v in series.values() if isinstance(v, (int, float))]
    if not vals:
        return None
    # monthly rate per 100k, averaged then annualized
    return (sum(vals) / len(vals)) * 12


def run(census_csv, tiger_geojson_path, out_path, top_n=100):
    global API_KEY
    API_KEY = get_credential('DATA_GOV_API_KEY')
    if not API_KEY:
        raise RuntimeError('DATA_GOV_API_KEY not found in credentials.txt')

    target_fips = pick_target_counties(census_csv, top_n, tiger_geojson_path)

    counties_gdf = gpd.read_file(str(tiger_geojson_path)).to_crs(epsg=4326)
    if 'GEOID' in counties_gdf.columns:
        counties_gdf['county_fips'] = counties_gdf['GEOID'].astype(str)
    name_col = 'NAME' if 'NAME' in counties_gdf.columns else 'NAMELSAD'
    state_col = 'STATE_NAME' if 'STATE_NAME' in counties_gdf.columns else None

    pop_df = pd.read_csv(census_csv, dtype={'county_fips': str})[['county_fips', 'B01003_001E']]

    # --- Hate crime: agency directory per state touched by target counties, then
    # per-agency hate-crime calls for agencies in those counties only. ---
    target_rows = counties_gdf[counties_gdf['county_fips'].isin(target_fips)]
    states_needed = sorted(target_rows[state_col].dropna().unique()) if state_col else []
    print(f'Fetching agency directories for {len(states_needed)} states...')

    agency_cache = {}
    for state_full in states_needed:
        abbr = US_STATE_ABBR.get(state_full)
        if not abbr:
            continue
        print(f'  {state_full} ({abbr})...')
        agency_cache[abbr] = fetch_agency_directory(abbr)

    hate_crime_rows = []
    for _, row in target_rows.iterrows():
        fips = row['county_fips']
        state_full = row[state_col] if state_col else None
        abbr = US_STATE_ABBR.get(state_full) if state_full else None
        county_norm = _normalize_county_name(row[name_col])
        agencies = agency_cache.get(abbr, [])
        matched_oris = [a['ori'] for a in agencies if _normalize_county_name(a.get('counties', '')) == county_norm]
        if not matched_oris:
            continue
        pop_row = pop_df[pop_df['county_fips'] == fips]
        population = float(pop_row['B01003_001E'].iloc[0]) if len(pop_row) else None
        totals = {col: 0 for col in BIAS_CATEGORY_TO_COL.values()}
        any_data = False
        print(f'  {row[name_col]}, {state_full}: {len(matched_oris)} agencies')
        for ori in matched_oris:
            bias_cats = fetch_hate_crime_for_ori(ori)
            if bias_cats is None:
                continue
            any_data = True
            for cat_name, col in BIAS_CATEGORY_TO_COL.items():
                totals[col] += bias_cats.get(cat_name, 0) or 0
        if not any_data or not population or population <= 0:
            continue
        years = 2  # DATE_FROM/DATE_TO spans 2022-2023
        out_row = {'county_fips': fips}
        for col, total in totals.items():
            out_row[col] = (total / years) / population * 100000  # incidents per 100k per year
        out_row['hate_crime_total'] = sum(totals.values()) / years / population * 100000
        hate_crime_rows.append(out_row)

    hate_crime_df = pd.DataFrame(hate_crime_rows)
    print(f'Hate crime: resolved data for {len(hate_crime_df)} of {len(target_fips)} target counties')

    # --- General offense rate: state-level, applied to every county nationwide. ---
    all_states = sorted(counties_gdf[state_col].dropna().unique()) if state_col else []
    print(f'Fetching state-level offense rates for {len(all_states)} states x {len(OFFENSE_CATEGORIES)} offenses...')
    state_rates = {}
    for state_full in all_states:
        abbr = US_STATE_ABBR.get(state_full)
        if not abbr:
            continue
        state_rates[state_full] = {}
        for offense, col in OFFENSE_CATEGORIES.items():
            state_rates[state_full][col] = fetch_state_offense_rate(abbr, offense)

    state_rates_df = pd.DataFrame([{'STATE_NAME': k, **v} for k, v in state_rates.items()])

    # --- Merge everything onto county geometry. ---
    merged = counties_gdf.merge(hate_crime_df, on='county_fips', how='left')
    if state_col:
        merged = merged.merge(state_rates_df, on=state_col, how='left')

    outp = Path(out_path)
    outp.parent.mkdir(parents=True, exist_ok=True)
    merged.to_file(str(outp), driver='GeoJSON')
    print(f'Wrote {len(merged)} county features to {outp}')
    return merged


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--census-csv', default=str(ROOT / 'data' / 'output' / 'census_counties_population.csv'))
    p.add_argument('--tiger', default=str(ROOT / 'data' / 'tiger_counties.geojson'))
    p.add_argument('--out', default=str(ROOT / 'data' / 'output' / 'crime_counties.geojson'))
    p.add_argument('--top-n', type=int, default=100)
    args = p.parse_args()
    run(args.census_csv, args.tiger, args.out, top_n=args.top_n)
