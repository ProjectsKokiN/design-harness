"""Reactの入口と運用修正を本物のコマンドで確かめる。"""
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import inbox_tool
import figma_freshness
import frame_io


class Improvements(unittest.TestCase):
    def test_joint_request(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            f, archive = root / 'tasks.md', root / 'archive.md'
            header = '## 2026-10-13 宛先: Mac mini / Windows [Mac mini:未対応 / Windows:未対応] — build'
            text = header + '\n\n本文\n\n## 未対応の依頼（索引）\n- 2026-10-13 宛先: Mac mini / Windows — **build**\n'
            f.write_text(text, encoding='utf-8')
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(inbox_tool.do_complete(f, archive, 'build'), 2)
                self.assertEqual(f.read_text(encoding='utf-8'), text)
                self.assertEqual(inbox_tool.do_complete(f, archive, 'build', 'Windows'), 0)
                self.assertFalse(archive.exists())
                current = f.read_text(encoding='utf-8')
                self.assertIn('Windows:完了', current)
                self.assertIn('**build**', current)
                self.assertFalse(inbox_tool.malformed_heads(current))
                self.assertEqual(inbox_tool.sections(current)[0][4], '未対応')
                self.assertEqual(inbox_tool.do_complete(f, archive, 'build', 'Mac mini'), 0)
                self.assertNotIn('build', f.read_text(encoding='utf-8'))
                self.assertIn('Windows:完了', archive.read_text(encoding='utf-8'))
            self.assertTrue(inbox_tool.malformed_heads(header.replace('Windows:未対応','Unknown:未対応')))

    def test_stroke_changes_digest(self):
        original = {'type': 'RECTANGLE', 'name': 'A', 'strokeWeight': 4}
        self.assertNotEqual(figma_freshness.node_digest(original), figma_freshness.node_digest({**original, 'strokeWeight': 8}))
        self.assertNotEqual(figma_freshness.node_digest(original), figma_freshness.node_digest({**original, 'strokeTopWeight': 2}))

    def test_react_entry_and_gaps(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'design').mkdir()
            rules = root / 'design/rules.json'
            rules.write_text(json.dumps({'extends': [str(ROOT / 'rules/web.json')],
                'file_extensions': ['.css'], 'expected_rules': 13, 'expected_targets': 1,
                'project_root': '..', 'rules': []}), encoding='utf-8')
            source = root / 'view.tsx'
            def run(code, argv=None):
                source.write_text(code, encoding='utf-8')
                return subprocess.run([sys.executable, str(ROOT / 'engine/design_check.py'), '--rules', str(rules), *(argv or [])],
                    input=json.dumps({'tool_input': {'file_path': str(source)}}), capture_output=True,
                    text=True, encoding='utf-8', env={**os.environ, 'HARNESS_SOURCE':'test'})
            r = run('const A=()=> <div style={{padding:16}}/>;')
            self.assertEqual(r.returncode, 2)
            self.assertIn('no-react-raw-values', r.stderr)
            self.assertIn('解析できた 1件', r.stdout)
            r = run('const A=()=> <div style={{padding:"var(--gap-xs)"}}/>;', ['--all'])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('未検証範囲', r.stdout)
            r = run('const A=()=> <div style={importedStyles}/>;')
            self.assertEqual(r.returncode, 2)
            self.assertIn('解析できなかった 1件', r.stdout)
            cfg = root / 'design/gaps.json'
            cfg.write_text(json.dumps({'rules':'design/rules.json'}),encoding='utf-8')
            r = subprocess.run([sys.executable,str(ROOT/'tools/gap_report.py'),'--config',str(cfg),'--no-write'],
                capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(r.returncode,2,r.stderr)
            self.assertIn('解析できなかった 1件',r.stdout)
            self.assertNotIn('コードが綺麗という意味',r.stdout)

    def test_directory_input(self):
        with tempfile.TemporaryDirectory() as td:
            r=subprocess.run([sys.executable,str(ROOT/'tools/design_md_check.py'),'--project',td,'--harness',td],
                capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(r.returncode,2)
            self.assertNotIn('Traceback',r.stderr)

    def test_missing_node(self):
        from unittest.mock import patch
        sys.path.insert(0,str(ROOT/'engine'))
        import react_web_check
        with patch.object(react_web_check.shutil,'which',return_value=None):
            r=react_web_check.analyze('<div/>','a.tsx')
            self.assertEqual(r['parsed'],0)
            self.assertEqual(r['unparsed'],1)


if __name__ == '__main__':
    unittest.main()
