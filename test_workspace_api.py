import requests
import time

endpoints = [
    'http://127.0.0.1:5577/api/workspaces',
    'http://127.0.0.1:5577/api/workspaces/formulas/presets',
    'http://127.0.0.1:5577/players/jamesle01/growth',
    'http://127.0.0.1:5577/teams',
]

for url in endpoints:
    try:
        r = requests.get(url, timeout=10)
        print(f'{r.status_code} {url}')
        if r.status_code != 200:
            print(f'  Body: {r.text[:200]}')
    except Exception as e:
        print(f'ERR {url}: {e}')
