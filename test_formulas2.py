import requests

try:
    r = requests.get('http://127.0.0.1:5577/api/workspaces/formulas/presets')
    print(f'Status: {r.status_code}')
    if r.status_code == 200:
        data = r.json()
        print(f'Total formulas: {len(data)}')
        categories = {}
        for f in data:
            cat = f['category']
            categories[cat] = categories.get(cat, 0) + 1
        print(f'Categories: {categories}')
        print()
        print('All formulas:')
        for f in data:
            print(f"  {f['id']:2d}: [{f['category']}] {f['name']}")
    else:
        print(f'Response: {r.text[:500]}')
except Exception as e:
    print(f'Error: {e}')
