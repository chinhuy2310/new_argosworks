import glob
import re

with open('web/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

html_ids = set(re.findall(r'id=["\']([^"\']+)["\']', html))
print(f"Total IDs found in index.html: {len(html_ids)}")

js_ids_by_file = {}
for fpath in glob.glob('web/js/*.js'):
    with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    found = set(re.findall(r'document\.getElementById\(["\']([^"\']+)["\']\)', content))
    js_ids_by_file[fpath] = found

all_js_ids = set().union(*js_ids_by_file.values())
missing = all_js_ids - html_ids

print(f"Total distinct IDs referenced in JS: {len(all_js_ids)}")
print(f"IDs in JS but missing in HTML ({len(missing)}):")

for m in sorted(missing):
    files = [f for f, ids in js_ids_by_file.items() if m in ids]
    print(f"  - {m} (in: {', '.join(files)})")
