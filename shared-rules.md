# Shared Rules — All Agents

These rules apply to EVERY agent working in the `web_app/` project. No exceptions.

---

## 1. File Ownership

Each file has exactly one owner agent. Agents must NOT modify files outside their ownership.

| File(s) | Owner Agent |
|---|---|
| `app/routes.py`, `app/__init__.py`, `app/auth.py`, `db.py`, `app/db/` | Backend Agent |
| `requirements.txt`, `run.py`, `app.py` | Backend Agent |
| `templates/*.html` | UI Agent |
| `tests/` | TDD Agent |
| Security config (`app/__init__.py` session/security section) | Security Agent |
| Performance/caching (`app/__init__.py`, `app/routes.py`) | Perf Agent |
| `agents/*.md` | Architect Agent |
| `shared-rules.md`, `definition-of-done.md`, `forbidden-actions.md`, `.agent.md` | Architect Agent |

**Cross-file reads are allowed** — agents can READ any file to understand context. Only WRITE access is restricted by ownership.

---

## 2. Communication Protocol

When multiple agents work simultaneously:

1. **Architect** sets file ownership BEFORE spawning agents
2. Agents must declare their file ownership in their report
3. If two agents try to modify the same file → Architect does the merge
4. After all agents complete → Architect validates against definition-of-done

---

## 3. Code Style Rules

### Python
- Use `from flask import request, session, redirect, url_for, flash, render_template` at top of file
- Use `cursor.execute("SELECT ... WHERE site_id = %s", (site_id,))` — parameterized, NEVER f-strings
- Use `check_password_hash(hashed, password)` from `werkzeug.security`
- Wrap database queries in try/except, flash friendly message on failure
- Route decorators: `@app.route()` before function, `@login_required` if protected

### Jinja2 Templates
- Use `{{ variable }}` for output (auto-escaped)
- Only use `| safe` for hardcoded static content (never user input)
- Use `{% block name %}...{% endblock %}` for reusable sections
- Loops: `{% for item in items %}...{% endfor %}`
- Conditionals: `{% if condition %}...{% endif %}`

### JavaScript
- Use `document.addEventListener("DOMContentLoaded", ...)` for init
- Use `chartInstances` global for chart registration
- Use `openChartModal()` and `closeChartModal()` from base.html
- NEVER add `window.addEventListener("resize", ...)` in page templates
- NEVER assign `window.xxxChart = xxx` in page templates

### CSS
- Use CSS variables from base.html (not hardcoded colors)
- Theme-aware: `[data-theme="dark"] .class { ... }`
- Mobile-first with `@media (max-width: 768px)`
- Use `rem` for spacing, `px` for borders and shadows

---

## 4. Error Handling

### Python routes
```python
try:
    data = get_data(from_date, to_date, sites)
except Exception as e:
    flash("Unable to load data. Please try again.")
    return render_template('page.html', chart_labels=[], ...)
```

### JavaScript
```javascript
try {
    renderChart();
} catch(e) {
    console.error('Chart render failed:', e);
    // show fallback or hide chart
}
```

### Never expose
- Stack traces to users
- Database column names or table structure
- Internal error codes
- File paths in error messages

---

## 5. Git / Version Control

- Never commit: `.env`, `*.pyc`, `__pycache__/`, `venv/`, `.sqlite`
- Write descriptive commit messages: `feat: add CSV export to 4G hourly KPI`
- Keep commits small and focused
- Before committing: run `python -m pytest tests/` to confirm no regressions

---

## 6. Dependency Management

- All new Python packages → add to `requirements.txt` with version pin
- All new CDN resources → add to `base.html` only
- Do NOT add packages without verifying they're needed
- Do NOT modify `venv/` or `site-packages/`

---

## 7. Environment Variables

Required environment variables for the app:
```bash
FLASK_SECRET_KEY=<your-secret-key>        # REQUIRED, no fallback
DATABASE_URL=<postgres-connection-string>  # For production DB
```

Never hardcode these values. Always use `os.environ.get()`.

---

## 8. Testing Requirement

- Before implementing any feature: write tests first (TDD Agent or regular agents following TDD)
- After any change: run existing tests to check for regression
- Test command: `python -m pytest tests/ -v` or `python -m unittest discover tests/`

---

## 9. Performance Budget

- Chart rendering: target < 2 seconds for 1000 data points
- Page load (no charts): target < 500ms
- Route response: target < 1 second for standard queries
- If a route is slower → investigate with profiling before optimizing

---

## 10. Accessibility

- All interactive elements must have `title` or `aria-label`
- Color contrast must meet WCAG AA standards (4.5:1 for text)
- Keyboard navigation must be possible (Tab, Enter, Escape)
- Charts must have alt-text descriptions in card subtitles

---

## 11. Breaking Changes Rule

Before making any change that could break existing functionality:
1. Document what the change does
2. Identify which existing features might break
3. Provide a migration path or fallback
4. Notify the user before implementing

---

## 12. Agent Coordination

When spawning multiple agents:
1. Architect declares file ownership map first
2. Each agent works only on their owned files
3. Agents READ other files freely but DO NOT WRITE
4. Architect handles any cross-file concerns
5. Architect validates final result

---

*Last updated: 2025-05-17*