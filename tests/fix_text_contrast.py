import os

def fix():
    # 1. Update web/js/home.js
    js_path = os.path.join('web', 'js', 'home.js')
    with open(js_path, 'r', encoding='utf-8') as f:
        js = f.read()

    old_pim_btn = '''<button type="button" class="portal-guest-btn" style="background:var(--surface-card, #ffffff); border:1px solid var(--border, #cbd5e1); color:var(--ink, #1e293b); width:100%; justify-content:center; padding:6px 12px; font-size:12.5px;" onclick="showTab(\\'pim\\')">카탈로그 바로가기 →</button>'''
    new_pim_btn = '''<button type="button" class="portal-guest-btn btn-secondary" style="width:100%; justify-content:center; padding:6px 12px; font-size:12.5px;" onclick="showTab(\\'pim\\')">카탈로그 바로가기 →</button>'''

    old_dash_btn = '''<button type="button" class="portal-guest-btn" style="background:var(--surface-card, #ffffff); border:1px solid var(--border, #cbd5e1); color:var(--ink, #1e293b); width:100%; justify-content:center; padding:6px 12px; font-size:12.5px;" onclick="showTab(\\'dash\\')">업무 보드 열기 →</button>'''
    new_dash_btn = '''<button type="button" class="portal-guest-btn btn-secondary" style="width:100%; justify-content:center; padding:6px 12px; font-size:12.5px;" onclick="showTab(\\'dash\\')">업무 보드 열기 →</button>'''

    assert old_pim_btn in js, "old_pim_btn not found"
    assert old_dash_btn in js, "old_dash_btn not found"

    js = js.replace(old_pim_btn, new_pim_btn, 1)
    js = js.replace(old_dash_btn, new_dash_btn, 1)

    with open(js_path, 'w', encoding='utf-8') as f:
        f.write(js)
    print("SUCCESS: web/js/home.js updated")

    # 2. Update web/css/home.css
    css_path = os.path.join('web', 'css', 'home.css')
    with open(css_path, 'r', encoding='utf-8') as f:
        css = f.read()

    dark_btn_rules = '''
/* Secondary Portal Button (PIM & Board) */
.portal-guest-btn.btn-secondary {
  background: #ffffff;
  color: #1e293b;
  border: 1px solid #cbd5e1;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}

.portal-guest-btn.btn-secondary:hover {
  background: #f8fafc;
  color: #0f172a;
  border-color: #94a3b8;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08);
}

[data-theme='dark'] .portal-guest-btn.btn-secondary {
  background: rgba(255, 255, 255, 0.1) !important;
  color: #f8fafc !important;
  border: 1px solid rgba(255, 255, 255, 0.22) !important;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
}

[data-theme='dark'] .portal-guest-btn.btn-secondary:hover {
  background: rgba(255, 255, 255, 0.18) !important;
  color: #ffffff !important;
  border-color: rgba(255, 255, 255, 0.35) !important;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.4);
}

[data-theme='dark'] .portal-task-title {
  color: #f1f5f9;
}

[data-theme='dark'] .portal-stat-num {
  color: #f1f5f9;
}

[data-theme='dark'] .portal-stat-item {
  background: rgba(15, 23, 42, 0.6);
  border-color: rgba(255, 255, 255, 0.08);
}

[data-theme='dark'] .portal-widget-footer {
  border-top-color: rgba(255, 255, 255, 0.08);
}

[data-theme='dark'] .portal-widget-footer a {
  color: #38bdf8;
}
'''
    if '\r\n' in css:
        dark_btn_rules = dark_btn_rules.replace('\n', '\r\n')
    css += dark_btn_rules

    with open(css_path, 'w', encoding='utf-8') as f:
        f.write(css)
    print("SUCCESS: web/css/home.css updated")

if __name__ == '__main__':
    fix()
