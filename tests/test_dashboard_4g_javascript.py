"""Check browser script syntax without requiring a live KPI database."""
import re
import subprocess
from pathlib import Path
from flask import Flask


def test_dashboard_4g_scripts_parse(tmp_path):
    root = Path(__file__).resolve().parents[1]
    app = Flask(__name__, template_folder=str(root / 'templates'))
    source = (root / 'templates' / 'dashboard_4g.html').read_text(encoding='utf-8')
    scripts = re.findall(r'<script\b[^>]*>(.*?)</script>', source, re.S)
    assert scripts
    with app.test_request_context('/dashboard_4g'):
        for index, script in enumerate(scripts):
            # Supply neutral JSON for server-injected chart datasets.
            script = re.sub(r'{{.*?}}', 'null', script, flags=re.S)
            script = app.jinja_env.from_string(script).render(query_done=False)
            target = tmp_path / f'dashboard_{index}.js'
            target.write_text(script, encoding='utf-8')
            result = subprocess.run(['node', '--check', str(target)], capture_output=True, text=True)
            assert result.returncode == 0, result.stderr
