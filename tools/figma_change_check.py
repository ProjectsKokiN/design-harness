#!/usr/bin/env python3
"""ノードIDで改名・単体から変異セットへの変更を見つけ、古い参照を探す（#169）。"""
import argparse
import json
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401
from figma_names import to_identifier


def nodes(doc):
    out = {}
    for key in ('frames', 'componentSets', 'singleComponents'):
        entries = doc.get(key) or {}
        if not isinstance(entries, dict):
            raise ValueError(f'{key}が辞書ではありません')
        for name, node in entries.items():
            nid = node.get('id') or (name if key == 'frames' else None)
            if not nid:
                raise ValueError(f'{key}/{name}にはIDがありません。改名を照合できません')
            if nid in out:
                raise ValueError(f'ノードIDが重複しています: {nid}')
            out[nid] = {'name': node.get('name') or name, 'kind': node.get('kind') or key}
            for variant in (node.get('variants') or {}).values():
                vid = variant.get('id')
                if not vid or vid == nid:
                    continue
                if vid in out:
                    raise ValueError(f'変異のIDが重複しています: {vid}')
                out[vid] = {'name': node.get('name') or name, 'kind': 'variant'}
    if not out:
        raise ValueError('ノードを照合できません（対象0件）')
    return out


def changes(before, after):
    old, new = nodes(before), nodes(after)
    return [{'id': k, 'before': old[k], 'after': new[k]} for k in old.keys() & new.keys() if old[k] != new[k]]


def references(changed, paths):
    found = []
    for path in paths:
        files = sorted(path.rglob('*')) if path.is_dir() else [path]
        for f in files:
            if not f.is_file() or set(f.parts) & {'.git', 'node_modules', 'archive', '__pycache__'}:
                continue
            if f.suffix not in ('.json', '.css', '.js', '.mjs', '.ts', '.tsx', '.jsx', '.py', '.dart', '.swift'):
                continue
            for i, line in enumerate(f.read_text(encoding='utf-8').splitlines(), 1):
                for c in changed:
                    old, new = c['before']['name'], c['after']['name']
                    # 名称と、既存の識別子変換を使ったクラス参照を候補として出す。
                    try:
                        ident = to_identifier(old)
                        css = re.sub(r'([a-z0-9])([A-Z])', r'\1-\2', ident).lower()
                        names = (old, ident, css)
                    except ValueError:
                        names = (old,)
                    if old != new and any(name in line for name in names):
                        found.append(f'{f.as_posix()}:{i}: {old} → {new}')
    return found


def self_test():
    import tempfile
    a = {'componentSets': {'Header/Works': {'id': '1:1', 'kind': 'single'}}}
    b = {'componentSets': {'Header': {'id': '1:1', 'kind': 'set'}}}
    c = changes(a, b)
    assert len(c) == 1 and c[0]['after']['kind'] == 'set'
    assert not changes(b, b)
    converted = {'componentSets': {'Header': {'id': '2:2', 'kind': 'set', 'variants': {'State=Default': {'id': '1:1'}}}}}
    assert changes(a, converted)[0]['after'] == {'name': 'Header', 'kind': 'variant'}
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / 'screen.json'
        f.write_text('{"component": "Header/Works"}', encoding='utf-8')
        assert references(c, [f])
        f.write_text('{"component": "Header"}', encoding='utf-8')
        assert not references(c, [f])
        before, after = Path(td) / 'before.json', Path(td) / 'after.json'
        before.write_text(json.dumps(a), encoding='utf-8')
        after.write_text(json.dumps(b), encoding='utf-8')
        assert main([]) == 2
        assert main(['--before', str(before), '--after', str(after)]) == 0
        f.write_text('Header/Works', encoding='utf-8')
        assert main(['--before', str(before), '--after', str(after), '--references', str(f)]) == 1
    try:
        nodes({'componentSets': {'A': {}}})
    except ValueError:
        pass
    else:
        raise AssertionError('ID無しを通しました')
    print('self-test: OK')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--before', type=Path)
    ap.add_argument('--after', type=Path)
    ap.add_argument('--references', nargs='*', type=Path, default=[])
    ap.add_argument("--self-test", action='store_true')
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    try:
        if not args.before or not args.after:
            raise ValueError('--beforeと--afterが必要です')
        c = changes(json.loads(args.before.read_text(encoding='utf-8')), json.loads(args.after.read_text(encoding='utf-8')))
        refs = references(c, args.references)
    except (OSError, ValueError, TypeError) as e:
        print(f'改名を照合できません: {e}', file=sys.stderr)
        return 2
    print(json.dumps({'changed': c, 'referenceCandidates': refs}, ensure_ascii=False))
    print('参照候補は文字列で検出します。候補の意味とIDが変わった部品の対応は未検証です')
    return 1 if refs else 0


if __name__ == '__main__':
    sys.exit(main())
