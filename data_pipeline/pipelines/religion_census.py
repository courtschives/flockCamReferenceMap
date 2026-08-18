"""Religion pipeline: ARDA/ASARB 2020 U.S. Religion Census, county level.

Source: usreligioncensus.org 2020 Religious Congregations and Membership
Study. Two files are used:
  - 2020_USRC_Summaries.xlsx ("2020 County Summary" sheet): county FIPS,
    2020 population estimate, and total adherents across all 372 reporting
    religious bodies.
  - 2020_USRC_Group_Detail.xlsx ("2020 Group by County" sheet): adherents
    per individual denomination/body per county (372 distinct groups).

The 372 individual groups are rolled up into recognizable tradition
"families" (Catholic, Evangelical Protestant, Mainline Protestant,
Historically Black Protestant, Latter-day Saints, Jehovah's Witness,
Orthodox Christian, Jewish, Muslim, Buddhist, Hindu, Other) using the
GROUP_FAMILY mapping below, which covers the ~60 groups that make up 98.8%
of national adherents; everything unmapped folds into 'other' rather than
being silently dropped.

Caveat baked into the output: RCMS counts adherents *claimed by a reporting
congregation*, not self-identified survey responses (unlike Pew/Gallup). The
residual (population minus total claimed adherents) is exposed as
pct_unclaimed - "not claimed by any reporting religious body" - which is a
methodologically different thing from "religiously unaffiliated" in a
Gallup-style poll, and should be labeled as such in the UI.
"""
from pathlib import Path
import pandas as pd
import geopandas as gpd

# name -> tradition family, covering the ~60 groups that are 98.8% of all
# national adherents (see data_pipeline/scripts/probe output). Anything not
# listed here (the long tail of smaller denominations) rolls into 'other'.
GROUP_FAMILY = {
    'Catholic Church': 'catholic',

    'Non-denominational Christian Churches': 'evangelical',
    'Southern Baptist Convention': 'evangelical',
    'Assemblies of God': 'evangelical',
    'Lutheran Church--Missouri Synod': 'evangelical',
    'Churches of Christ': 'evangelical',
    'Christian Churches and Churches of Christ': 'evangelical',
    'Seventh-day Adventist Church': 'evangelical',
    'Church of the Nazarene': 'evangelical',
    'Church of God (Cleveland, Tennessee)': 'evangelical',
    'Church of God (Anderson, Indiana)': 'evangelical',
    'Christian and Missionary Alliance': 'evangelical',
    'Wisconsin Evangelical Lutheran Synod': 'evangelical',
    'Presbyterian Church in America': 'evangelical',
    'Foursquare Gospel, International Church of the': 'evangelical',
    'Wesleyan Church': 'evangelical',
    'Full Gospel Christian Assemblies International': 'evangelical',
    'National Association of Free Will Baptists': 'evangelical',
    'Vineyard USA': 'evangelical',
    'Christian Reformed Church in North America': 'evangelical',
    'Evangelical Covenant Church': 'evangelical',
    'American Baptist Association': 'evangelical',
    'Salvation Army': 'evangelical',
    'Lutheran Congregations in Mission for Christ': 'evangelical',

    'United Methodist Church': 'mainline',
    'Evangelical Lutheran Church in America': 'mainline',
    'Episcopal Church': 'mainline',
    'Presbyterian Church (U.S.A.)': 'mainline',
    'American Baptist Churches in the USA': 'mainline',
    'United Church of Christ': 'mainline',
    'Christian Church (Disciples of Christ)': 'mainline',
    'Reformed Church in America': 'mainline',

    'National Missionary Baptist Convention, Inc.': 'black_protestant',
    'National Baptist Convention, USA, Inc.': 'black_protestant',
    'African Methodist Episcopal Church': 'black_protestant',
    'African Methodist Episcopal Zion Church': 'black_protestant',
    'Church of God in Christ': 'black_protestant',
    'Christian Methodist Episcopal Church': 'black_protestant',
    'Progressive National Baptist Convention, Inc.': 'black_protestant',
    'National Baptist Convention of America, Inc.': 'black_protestant',
    'Full Gospel Baptist Church Fellowship': 'black_protestant',

    'Church of Jesus Christ of Latter-day Saints': 'lds',
    "Jehovah's Witnesses": 'jehovahs_witness',

    'Greek Orthodox Archdiocese of America': 'orthodox_christian',
    'Coptic Orthodox Church': 'orthodox_christian',
    'Ethiopian Orthodox': 'orthodox_christian',
    'Armenian Church of North America (Catholicosate of Etchmiadzin)': 'orthodox_christian',

    'Orthodox Judaism': 'jewish',
    'Reform Judaism': 'jewish',
    'Conservative Judaism': 'jewish',

    'Muslim Estimate': 'muslim',

    'Mahayana Buddhist': 'buddhist',
    'Theravada Buddhist': 'buddhist',
    'Vajarayana Buddhist': 'buddhist',

    'Hindu Temples': 'hindu',
    'Hindu Yoga and Meditation': 'hindu',
}

FAMILY_LABELS = {
    'catholic': 'Catholic',
    'evangelical': 'Evangelical Protestant',
    'mainline': 'Mainline Protestant',
    'black_protestant': 'Historically Black Protestant',
    'lds': 'Latter-day Saints',
    'jehovahs_witness': "Jehovah's Witness",
    'orthodox_christian': 'Orthodox Christian',
    'jewish': 'Jewish',
    'muslim': 'Muslim',
    'buddhist': 'Buddhist',
    'hindu': 'Hindu',
    'other': 'Other Religions',
}


def run(group_detail_xlsx, county_summary_xlsx, out_path, tiger_geojson_path=None):
    repo_root = Path(__file__).resolve().parents[2]
    if tiger_geojson_path is None:
        tiger_geojson_path = repo_root / 'data' / 'tiger_counties.geojson'

    summary = pd.read_excel(county_summary_xlsx, sheet_name='2020 County Summary')
    summary = summary.rename(columns={'FIPS': 'county_fips', '2020 Population': 'religion_population',
                                       'Adherents': 'total_adherents'})
    summary['county_fips'] = summary['county_fips'].astype(str).str.zfill(5)
    summary = summary[['county_fips', 'religion_population', 'total_adherents']]

    detail = pd.read_excel(group_detail_xlsx, sheet_name='2020 Group by County')
    detail['county_fips'] = detail['FIPS'].astype(str).str.zfill(5)
    detail['family'] = detail['Group Name'].map(GROUP_FAMILY).fillna('other')
    by_family = detail.groupby(['county_fips', 'family'], as_index=False)['Adherents'].sum()
    wide = by_family.pivot(index='county_fips', columns='family', values='Adherents').fillna(0).reset_index()
    wide.columns = ['county_fips'] + [f'adherents_{c}' for c in wide.columns if c != 'county_fips']

    merged = summary.merge(wide, on='county_fips', how='left')
    for col in [f'adherents_{k}' for k in FAMILY_LABELS if k != 'other'] + ['adherents_other']:
        if col not in merged.columns:
            merged[col] = 0
        merged[col] = merged[col].fillna(0)

    # Clipped to [0, 100]: a handful of counties report more claimed adherents
    # in a family (or in total) than ARDA's own population estimate for that
    # county - commuter congregations, institutional populations (e.g. mission
    # organizations), and other known RCMS methodology quirks at fine geography.
    # Without clipping this produces nonsense like "113% Latter-day Saints".
    pop = pd.to_numeric(merged['religion_population'], errors='coerce')
    for key in FAMILY_LABELS:
        count_col = f'adherents_{key}'
        pct_col = f'pct_{key}'
        merged[pct_col] = (merged[count_col] / pop * 100).where(pop > 0).clip(upper=100)

    total_adherents = pd.to_numeric(merged['total_adherents'], errors='coerce').fillna(0)
    merged['pct_any_affiliation'] = (total_adherents / pop * 100).where(pop > 0).clip(upper=100)
    # RCMS-methodology residual: population not claimed as an adherent by any
    # reporting congregation. Clipped at 0 - a handful of counties report
    # more claimed adherents than resident population (commuter congregations,
    # methodology quirks), which would otherwise go negative and be nonsense.
    merged['pct_unclaimed'] = ((pop - total_adherents) / pop * 100).where(pop > 0).clip(lower=0)

    counties = gpd.read_file(str(tiger_geojson_path)).to_crs(epsg=4326)
    if 'GEOID' in counties.columns:
        counties['county_fips'] = counties['GEOID'].astype(str)
    else:
        counties['county_fips'] = counties['STATEFP'].astype(str).str.zfill(2) + counties['COUNTYFP'].astype(str).str.zfill(3)

    out_gdf = counties.merge(merged, on='county_fips', how='left')

    outp = Path(out_path)
    outp.parent.mkdir(parents=True, exist_ok=True)
    out_gdf.to_file(str(outp), driver='GeoJSON')
    print(f'Wrote {len(out_gdf)} county features to {outp}')
    return out_gdf


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--group-detail', required=True, help='path to 2020_USRC_Group_Detail.xlsx')
    p.add_argument('--county-summary', required=True, help='path to 2020_USRC_Summaries.xlsx')
    p.add_argument('--out', required=True, help='output GeoJSON path')
    p.add_argument('--tiger', help='optional path to tiger_counties.geojson')
    args = p.parse_args()
    run(args.group_detail, args.county_summary, args.out, tiger_geojson_path=args.tiger)
