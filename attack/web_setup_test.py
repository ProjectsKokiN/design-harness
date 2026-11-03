"""Web導入文書の規則例を本物のエンジンで試す（#165）。"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    source = (ROOT / 'docs/web-setup.md').read_text(encoding='utf-8')
    rules = json.loads(re.findall(r'```json\n(.*?)\n```', source, re.S)[0])
    rules['extends'] = [str(ROOT / 'rules/web.json')]
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / 'design').mkdir()
        rules['expected_targets'] = 1
        rules['project_root'] = '..'
        p = root / 'design/rules.json'
        p.write_text(json.dumps(rules), encoding='utf-8')
        view = root / 'view.tsx'
        for code, expected in [('const A=()=> <div style={{padding:"var(--gap-xs)"}}/>;', 0),
                               ('const A=()=> <div style={{padding:16}}/>;', 2),
                               ('const A=()=> <div style={externalStyles}/>;', 2)]:
            view.write_text(code, encoding='utf-8')
            r = subprocess.run([sys.executable, str(ROOT / 'engine/design_check.py'), '--rules', str(p), '--all'],
                capture_output=True, text=True, encoding='utf-8', env={**os.environ, 'HARNESS_SOURCE': 'test'})
            if r.returncode != expected:
                raise AssertionError(r.stdout + r.stderr)
    print('Web導入例: 正常・違反・未解析の3ケースが期待どおりです')
    return 0


if __name__ == '__main__':
    sys.exit(main())
