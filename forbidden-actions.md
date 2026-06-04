# Forbidden Actions — All Agents

🚫 **These actions are PROHIBITED. Violations will be reported to the user.**

---

## Security — Zero Tolerance

### 🔴 SQL Injection — NEVER
```python
# ❌ FORBIDDEN — string concatenation for SQL
cursor.execute(f"SELECT * FROM table WHERE site = '{site}'")

# ✅ REQUIRED — parameterized query
cursor.execute("SELECT * FROM table WHERE site = %s", (site,))
```

### 🔴 Hardcoded Secrets — NEVER
```python
# ❌ FORBIDDEN — hardcoded secret key
app.config['SECRET_KEY'] = 'secret123'

# ✅ REQUIRED — environment variable
import os
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY')
```

### 🔴 XSS via `| safe` — NEVER on user input
```html
<!-- ❌ FORBIDDEN — | safe on user-controlled content -->
<div>{{ user_input | safe }}</div>

<!-- ✅ REQUIRED — Jinja2 auto-escapes by default -->
<div>{{ user_input }}</div>
```

### 🔴 Commit Credentials — NEVER
- Never commit `.env` files
- Never commit `*.sqlite` database files
- Never commit API keys or passwords in code
- Never commit session cookies or JWT tokens

---

## Performance — Prohibited

### 🔴 Double-Resize Bug in Templates — NEVER
```html
<!-- ❌ FORBIDDEN in page templates -->
window.addEventListener("resize", function() {
    charts.forEach(function(c) { c.resize(); });
});
```
**Why:** `base.html`'s `toggleSidebar()` already dispatches `resize` event. This causes double-resize → lag.

**Fix:** Let base.html handle resize via `chartInstances`. Do NOT add resize listeners in page templates.

### 🔴 Global Chart Assignments in Templates — NEVER
```html
<!-- ❌ FORBIDDEN in page templates -->
window.payloadChart = chart;
window.xxxChart = chart;
```
**Why:** `toggleSidebar()` iterates both `chartInstances` AND legacy `window.payloadChart` globals — double-resize.

**Fix:** Register charts ONLY to `chartInstances`, not `window.*` globals.

---

## Architecture — Prohibited

### 🔴 Modify Another Agent's Files — NEVER

| Your agent | You CANNOT modify |
|---|---|
| TDD Agent | `app/`, `templates/`, `db.py` directly (only tests) |
| Backend Agent | `templates/` |
| UI Agent | `app/`, `db.py`, `requirements.txt` |
| Perf Agent | `templates/` (only JS/Chart.js config) |
| Security Agent | `templates/` (only security-related parts) |
| Any Agent | `agents/`, `shared-rules.md`, `definition-of-done.md`, `forbidden-actions.md` |

### 🔴 Duplicate CDN Includes — NEVER
All CDN resources (Chart.js, Font Awesome, Google Fonts) go in `templates/base.html` ONLY.

```html
<!-- ❌ FORBIDDEN — CDN in child templates -->
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<link href="https://fonts.googleapis.com/css?family=Font+Awesome">
```

```html
<!-- ✅ REQUIRED — CDN in base.html only, child templates extend it -->
{% extends "base.html" %}
<!-- base.html already includes Chart.js, Font Awesome, Google Fonts -->
```

### 🔴 Remove Authentication — NEVER
Never remove or comment out auth checks to "make testing easier."

```python
# ❌ FORBIDDEN — commenting out auth for convenience
# @app.route('/protected')
# def protected():
#     return "secret"
```

### 🔴 Breaking Changes Without Migration — NEVER
Do not change route URLs, change data shapes, or remove features without:
1. Documenting the change
2. Providing a fallback or migration path
3. Notifying the user

---

## Code Quality — Prohibited

### 🔴 Expose Stack Traces to Users — NEVER
```python
# ❌ FORBIDDEN in production
except Exception as e:
    return f"Error: {e}", 500
```

```python
# ✅ REQUIRED — user-friendly error
except Exception as e:
    flash("Something went wrong. Please try again.")
    return redirect(url_for('page'))
```

### 🔴 Bare `except:` Clauses — Discouraged
```python
# ⚠️ DISCOURAGED — catches everything including KeyboardInterrupt
except:
    pass

# ✅ PREFERRED — specific exception
except ValueError:
    flash("Invalid input")
except Exception:
    flash("Something went wrong")
```

### 🔴 Magic Numbers — Discouraged
```python
# ⚠️ DISCOURAGED
if points > 720:

# ✅ PREFERRED
MAX_HOURLY_POINTS = 720
if points > MAX_HOURLY_POINTS:
```

---

## Environment — Prohibited

### 🔴 Modify venv/ or site-packages/ — NEVER
- Do not install packages directly into venv
- Do not modify files in `venv/Lib/site-packages/`
- Use `pip install` commands and update `requirements.txt`

### 🔴 Remove .gitignore items from gitignore — NEVER
- Keep `.env` in gitignore
- Keep `venv/` in gitignore
- Keep `__pycache__/` in gitignore

---

## Quick Reference Card

| Forbidden Action | Severity | Alternative |
|---|---|---|
| SQL string concat | 🔴 Critical | `cursor.execute(..., (var,))` |
| Hardcoded secret | 🔴 Critical | `os.environ.get('KEY')` |
| `| safe` on user input | 🔴 Critical | Auto-escape with `{{ var }}` |
| Commit .env | 🔴 Critical | Add to .gitignore |
| `window.addEventListener("resize")` in templates | 🔴 Critical | Let base.html handle via chartInstances |
| `window.xxxChart = xxx` in templates | 🔴 Critical | Register to `chartInstances` only |
| Duplicate CDN includes | 🔴 Critical | Put in base.html only |
| Remove auth checks | 🔴 Critical | Keep `@login_required` |
| Expose stack traces | 🔴 Critical | Custom error handler + flash |
| Modify another agent's files | 🔴 Critical | Respect file ownership |
| Breaking changes | 🔴 High | Migration path + notify user |
| Aggressive caching (stale data) | 🔴 High | Cache with short TTL |
| Bare `except:` clauses | 🟡 Medium | `except SpecificException:` |

---

*Last updated: 2025-05-17*