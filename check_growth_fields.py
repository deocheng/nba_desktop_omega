import subprocess
import json

result = subprocess.run(
    ['powershell', '-Command', '(Invoke-WebRequest -Uri "http://127.0.0.1:5577/players/jamesle01/growth" -UseBasicParsing).Content'],
    capture_output=True,
    text=True
)
data = json.loads(result.stdout)

print("=== Bio fields ===")
bio = data.get('bio', {})
for k, v in bio.items():
    print(f"  {k}: {type(v).__name__}")

print("\n=== Season fields (first season) ===")
seasons = data.get('seasons', [])
if seasons:
    for k, v in seasons[0].items():
        print(f"  {k}: {type(v).__name__}")

print("\n=== Shooting fields ===")
shooting = data.get('shooting', [])
if shooting:
    for k, v in shooting[0].items():
        print(f"  {k}: {type(v).__name__}")
