import os

def update_home_theme():
    css_path = os.path.join('web', 'css', 'home.css')
    with open(css_path, 'r', encoding='utf-8') as f:
        css = f.read()

    # Find the secondary button rule section and replace with robust dual-mode selectors
    marker = '/* Secondary Portal Button (PIM & Board) */'
    if marker in css:
        parts = css.split(marker)
        css = parts[0]

    robust_rules = '''/* Secondary Portal Button (PIM & Board) */
.portal-guest-btn.btn-secondary {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: #ffffff;
  color: #1e293b;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  padding: 6px 14px;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}

.portal-guest-btn.btn-secondary:hover {
  background: #f8fafc;
  color: #0284c7;
  border-color: #0284c7;
  box-shadow: 0 2px 6px rgba(2, 132, 199, 0.15);
}

/* Dark Mode - covers both data-theme="dark" and :root:not([data-theme="light"]) */
:root:not([data-theme="light"]) .portal-guest-btn.btn-secondary,
[data-theme='dark'] .portal-guest-btn.btn-secondary {
  background: rgba(255, 255, 255, 0.09) !important;
  color: #f8fafc !important;
  border: 1px solid rgba(255, 255, 255, 0.22) !important;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.35) !important;
}

:root:not([data-theme="light"]) .portal-guest-btn.btn-secondary:hover,
[data-theme='dark'] .portal-guest-btn.btn-secondary:hover {
  background: rgba(255, 255, 255, 0.18) !important;
  color: #38bdf8 !important;
  border-color: #38bdf8 !important;
  box-shadow: 0 2px 10px rgba(56, 189, 248, 0.25) !important;
}

:root:not([data-theme="light"]) .portal-card-title,
[data-theme='dark'] .portal-card-title {
  color: #f8fafc !important;
}

:root:not([data-theme="light"]) .portal-widget-card p,
[data-theme='dark'] .portal-widget-card p {
  color: #cbd5e1 !important;
}

:root:not([data-theme="light"]) .portal-task-title,
[data-theme='dark'] .portal-task-title {
  color: #f1f5f9 !important;
}

:root:not([data-theme="light"]) .portal-stat-num,
[data-theme='dark'] .portal-stat-num {
  color: #f1f5f9 !important;
}

:root:not([data-theme="light"]) .portal-stat-item,
[data-theme='dark'] .portal-stat-item {
  background: rgba(15, 23, 42, 0.6) !important;
  border-color: rgba(255, 255, 255, 0.08) !important;
}

:root:not([data-theme="light"]) .portal-widget-footer,
[data-theme='dark'] .portal-widget-footer {
  border-top-color: rgba(255, 255, 255, 0.08) !important;
}

:root:not([data-theme="light"]) .portal-widget-footer a,
[data-theme='dark'] .portal-widget-footer a {
  color: #38bdf8 !important;
}
'''
    if '\r\n' in css:
        robust_rules = robust_rules.replace('\n', '\r\n')
    css += robust_rules

    with open(css_path, 'w', encoding='utf-8') as f:
        f.write(css)
    print("SUCCESS: web/css/home.css updated with dual dark mode selectors")

if __name__ == '__main__':
    update_home_theme()
