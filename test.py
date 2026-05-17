import json
with open('backend/data/elders/W001.json', encoding='utf-8') as f:
    d = json.load(f)
print(d.get('elder_biography', {}).get('content', '無'))