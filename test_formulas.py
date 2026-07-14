import urllib.request
import json

r = urllib.request.urlopen('http://127.0.0.1:5577/api/workspaces/formulas/presets')
data = json.loads(r.read())

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
    print(f"        {f['description'][:50]}...")
