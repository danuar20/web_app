# Migration Notes

## Files to Remove (Deprecated)

The following files are deprecated and should be removed:

1. **`app.py`** — Old monolithic Flask app
   - Replaced by: `app/__init__.py` (app factory pattern)
   - Status: DEPRECATED ❌

2. **`db.py`** — Old database connection
   - Replaced by: `app/db/db_webapp.py`, `app/db/db_pumaz.py`
   - Status: DEPRECATED ❌

3. **`test_db_old.py`** — Old database test file
   - Status: OBSOLETE ❌

These files used old code patterns and should not be used. The new modular structure in `app/` is the correct approach.

## Migration Completed ✅

- ✅ Converted to app factory pattern (`app/__init__.py`)
- ✅ Separated database connections to `app/db/`
- ✅ Moved routes to `app/routes.py` as Blueprint
- ✅ Added environment variable support (`.env`)
- ✅ Updated credentials management

---

## When You're Ready

To remove these deprecated files:

```bash
rm app.py
rm db.py
rm test_db_old.py
```

But keep `test_db.py` if it's still useful for testing.
