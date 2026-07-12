from fastapi.testclient import TestClient
from backend.app import create_app

app = create_app()
client = TestClient(app)

response = client.get("/api/workspaces/formulas/presets")
print(f"Status: {response.status_code}")
if response.status_code == 200:
    data = response.json()
    print(f"Total formulas: {len(data)}")
    categories = {}
    for f in data:
        cat = f['category']
        categories[cat] = categories.get(cat, 0) + 1
    print(f"Categories: {categories}")
    print()
    print("All formulas:")
    for f in data:
        print(f"  {f['id']:2d}: [{f['category']}] {f['name']}")
        print(f"        {f['description'][:60]}...")
else:
    print(f"Response: {response.text[:500]}")
