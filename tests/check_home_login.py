import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('web/index.html', 'r', encoding='utf-8') as f:
    text = f.read()

import re
m = re.search(r'<section[^>]+id=["\']viewHome["\'].*?</section>', text, re.DOTALL)
if m:
    lines = m.group(0).splitlines()
    for i, line in enumerate(lines):
        if any(k in line.lower() for k in ['login', '로그인']):
            print(f'{i+1}: {line.strip()[:100]}')
else:
    print('viewHome not found')
