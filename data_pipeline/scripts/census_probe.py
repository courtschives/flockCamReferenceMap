from data_pipeline.utils.credentials import get_credential
import requests

API = 'https://api.census.gov/data/2024/acs/acs5'
key = get_credential('CENSUS_API_KEY')
params = {'get': 'B01003_001E', 'for': 'county:075', 'in': 'state:06', 'key': key}
try:
    r = requests.get(API, params=params, timeout=30)
    print('status=', r.status_code)
    print('content-type=', r.headers.get('content-type'))
    text = r.text
    print('body-snippet:')
    print(text[:800])
except Exception as e:
    print('ERROR', type(e).__name__, e)
