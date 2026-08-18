import requests

query = """[out:json];
node[\"surveillance:type\"=\"ALPR\"](37.70,-122.52,37.82,-122.35);
out tags;"""

resp = requests.post(
    'https://overpass-api.de/api/interpreter',
    data={'data': query},
    headers={'User-Agent': 'FlockMapTest/1.0'},
    timeout=60,
)
print('status=', resp.status_code)
print('content-type=', resp.headers.get('content-type'))
print(resp.text[:1000])
