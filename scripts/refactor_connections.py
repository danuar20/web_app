"""
Batch refactor script: Add db_query import and replace bare connection patterns
in all route files that haven't been updated yet.

This script:
1. Adds 'db_query' to the import from ._utils
2. Replaces patterns like `conn = get_postgres_connection(); cur = conn.cursor()`
   with `with db_query() as (conn, cur):`
3. Removes manual `cur.close(); conn.close()` lines

Run from the web_app directory: python scripts/refactor_connections.py
"""
import os
import re

ROUTES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app", "routes")
ALREADY_DONE = {"_utils.py", "__init__.py", "kpi_4g_hourly_routes.py", "auth_routes.py", "nettilt3d_routes.py"}

def refactor_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original = content
    basename = os.path.basename(filepath)
    
    # Skip if already has db_query import
    if 'db_query' in content:
        print(f"  SKIP {basename} (already has db_query)")
        return False
    
    # 1. Add db_query to the import from ._utils
    # Match patterns like: from ._utils import login_required, _no_cache, json_response
    import_pattern = r'(from \._utils import )([^\n]+)'
    match = re.search(import_pattern, content)
    if match:
        existing_imports = match.group(2).rstrip()
        if 'db_query' not in existing_imports:
            new_imports = existing_imports + ', db_query'
            content = content[:match.start()] + match.group(1) + new_imports + content[match.end():]
    else:
        print(f"  WARN {basename}: no _utils import found, skipping")
        return False
    
    # 2. Replace `conn = get_postgres_connection()` + next-line `cur = conn.cursor()` 
    # with `with db_query() as (conn, cur):`
    # This is complex because of varying indentation, so we handle common patterns
    
    # Pattern A: `conn = get_postgres_connection()\n            cur = conn.cursor()`
    content = re.sub(
        r'(\s+)conn = get_postgres_connection\(\)\n\s+cur\s*=\s*conn\.cursor\(\)',
        r'\1with db_query() as (conn, cur):',
        content
    )
    
    # Pattern B: `conn = get_postgres_connection(); cur = conn.cursor()`  (same line)
    content = re.sub(
        r'(\s+)conn = get_postgres_connection\(\)\s*;\s*cur\s*=\s*conn\.cursor\(\)',
        r'\1with db_query() as (conn, cur):',
        content
    )
    
    # Pattern C: standalone `conn = get_postgres_connection()` (without following cur line)
    # These need the cursor added — but we'll handle these manually or leave as-is
    
    # 3. Remove standalone `cur.close(); conn.close()` or `cur.close()\n...conn.close()`
    content = re.sub(r'\n\s+cur\.close\(\)\s*;\s*conn\.close\(\)\s*\n', '\n', content)
    content = re.sub(r'\n\s+cur\.close\(\)\s*\n\s+conn\.close\(\)\s*\n', '\n', content)
    
    # 4. Remove manual cleanup in except blocks
    # Pattern: `if conn: conn.rollback()\n if cur: cur.close()\n if conn: conn.close()`
    content = re.sub(
        r'\n\s+if conn:\s*conn\.rollback\(\)\s*\n\s+if cur:\s*cur\.close\(\)\s*\n\s+if conn:\s*conn\.close\(\)\s*\n',
        '\n',
        content
    )
    # Pattern: multi-line with try
    content = re.sub(
        r'\n\s+if conn:\s*\n\s+try:\s*conn\.rollback\(\)\s*\n\s+except:\s*pass\s*\n\s+if cur:\s*cur\.close\(\)\s*\n\s+if conn:\s*conn\.close\(\)\s*\n',
        '\n',
        content
    )
    
    if content != original:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"  DONE {basename}")
        return True
    else:
        print(f"  NO CHANGES {basename}")
        return False

def main():
    print("=== Batch Refactor: db_query context manager ===\n")
    
    files = [f for f in os.listdir(ROUTES_DIR) 
             if f.endswith('.py') and f not in ALREADY_DONE and not f.startswith('__')]
    
    changed = 0
    for fname in sorted(files):
        filepath = os.path.join(ROUTES_DIR, fname)
        if refactor_file(filepath):
            changed += 1
    
    print(f"\n=== Done: {changed}/{len(files)} files modified ===")

if __name__ == "__main__":
    main()
