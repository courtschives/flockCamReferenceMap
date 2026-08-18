"""Quick diagnostic: probe Census ACS API response for B01003_001E.

Run with the `flockmap` conda env. Prints status, headers, and a body preview.
"""
import requests
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
cred_path = ROOT / 'credentials.txt'

def read_key():
    if not cred_path.exists():
        print('credentials.txt not found at', cred_path)
        return None
    for line in cred_path.read_text().splitlines():
        if line.strip().startswith('CENSUS_API_KEY'):
            _, val = line.split('=', 1)
            return val.strip()
    return None


def main():
    key = read_key()
    if not key:
        print('Census key not found in credentials.txt')
        return
    url = 'https://api.census.gov/data/2024/acs/acs5'
    params = {'get': 'B01003_001E,state,county', 'for': 'county:*', 'key': key}
    print('Requesting:', url)
    try:
        resp = requests.get(url, params=params, headers={'User-Agent':'FlockMap/1.0','Accept':'application/json'}, timeout=60)
        print('Status:', resp.status_code)
        print('Content-Type:', resp.headers.get('Content-Type'))
        text = resp.text or ''
        print('Body length:', len(text))
        preview = text[:1000]
        print('Body preview (first 1000 chars):')
        print(preview)
    except Exception as e:
        print('Request exception:', type(e).__name__, e)


if __name__ == '__main__':
    main()
