import sys
sys.stdout.reconfigure(encoding='utf-8')
from bs4 import BeautifulSoup

with open('web/index.html', 'r', encoding='utf-8') as f:
    soup = BeautifulSoup(f.read(), 'html.parser')

items = []
for tag in soup.find_all(['button', 'a', 'input']):
    if tag.name == 'input' and tag.get('type') not in ['button', 'submit', 'checkbox', 'radio']:
        continue
    
    # find enclosing container with id
    curr = tag.parent
    container_id = 'global'
    while curr:
        if curr.get('id'):
            container_id = curr.get('id')
            break
        curr = curr.parent
        
    elem_id = tag.get('id', '')
    elem_class = ' '.join(tag.get('class', []))
    elem_text = tag.text.strip().replace('\n', ' ')[:40]
    title = tag.get('title', '')
    data_target = tag.get('data-target', '')
    
    items.append({
        'tag': tag.name,
        'container': container_id,
        'id': elem_id,
        'class': elem_class,
        'text': elem_text or title or data_target,
    })

print(f"Total clickable elements found: {len(items)}\n")

containers = {}
for it in items:
    containers.setdefault(it['container'], []).append(it)

for c_id, c_items in sorted(containers.items(), key=lambda x: -len(x[1])):
    print(f"=== Container [{c_id}]: {len(c_items)} clickable items ===")
    for it in c_items[:5]:
        desc = it['id'] or it['class'] or '(no id/class)'
        print(f"  - [{it['tag']}] #{desc} : \"{it['text']}\"")
    if len(c_items) > 5:
        print(f"  ... and {len(c_items) - 5} more items")
    print()
