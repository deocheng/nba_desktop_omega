import requests

r = requests.get('http://127.0.0.1:5577/players/jamesle01/growth')
data = r.json()

print("=== Bio fields ===")
bio = data.get('bio', {})
print(list(bio.keys()))

print("\n=== Season fields (first season) ===")
seasons = data.get('seasons', [])
if seasons:
    print(list(seasons[0].keys()))

print("\n=== Shooting fields ===")
shooting = data.get('shooting', [])
if shooting:
    print(list(shooting[0].keys()))
