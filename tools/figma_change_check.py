#!/usr/bin/env python3
"""ノードIDで改名・単体から変異セットへの変更を見つけ、古い参照を探す（#169）。

**作り直しも見つける**（候補6・2026-11-03）。部品・変数を作り直すと、ID も key も変わるので、
ID で見る改名の照合には現れない。**名前が同じなのに key が変わったもの**を名指しする
（作り直すと、使う側の画面とのつながりが切れる。外部の実践例 ds-base-ui の教訓）。
key は書き出し器が 2026-11-03 から書く。どちらかの書き出しに key が無ければ「見ていない」と言う。
変数の書き出し（collections）どうしなら、改名の照合は飛ばして key だけを見る。
"""
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


def keys_by_name(doc):
    """名前 → key。部品セット・変異（`セット/変異`）・変数（`コレクション/名前`）。"""
    out = {}
    for key in ('componentSets', 'singleComponents'):
        for name, node in (doc.get(key) or {}).items():
            if node.get('key'):
                out[f'部品 {name}'] = node['key']
            for vname, v in (node.get('variants') or {}).items():
                if v.get('key'):
                    out[f'部品 {name}/{vname}'] = v['key']
    cols = doc.get('collections') or {}
    for cname, col in (cols.items() if isinstance(cols, dict) else ()):
        for v in (col.get('variables') or []) if isinstance(col, dict) else []:
            if isinstance(v, dict) and v.get('key') and v.get('name'):
                out[f'変数 {cname}/{v["name"]}'] = v['key']
    return out


def recreated(before, after):
    """`(作り直されたもの, 見たか)`。どちらかに key が1つも無ければ見ていない。"""
    old, new = keys_by_name(before), keys_by_name(after)
    if not old or not new:
        return [], False
    return [{'name': n, 'before': old[n], 'after': new[n]}
            for n in sorted(old.keys() & new.keys()) if old[n] != new[n]], True


def _variables_only(doc):
    return 'collections' in doc and not any(k in doc for k in ('frames', 'componentSets', 'singleComponents'))


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
    # **作り直し**（候補6）: 同じ名前で key が変わったものを名指しする
    ka = {'componentSets': {'Button': {'id': '1:1', 'key': 'K1', 'variants': {'Size=M': {'id': '1:2', 'key': 'V1'}}}}}
    kb = {'componentSets': {'Button': {'id': '9:9', 'key': 'K2', 'variants': {'Size=M': {'id': '9:8', 'key': 'V2'}}}}}
    r, seen = recreated(ka, kb)
    assert seen and {x['name'] for x in r} == {'部品 Button', '部品 Button/Size=M'}, r
    assert recreated(ka, ka) == ([], True)
    assert recreated(a, b) == ([], False)            # key が無い書き出しは「見ていない」
    va = {'collections': {'色': {'variables': [{'name': 'Frame/Default', 'key': 'A'}]}}}
    vb = {'collections': {'色': {'variables': [{'name': 'Frame/Default', 'key': 'B'}]}}}
    assert recreated(va, vb)[0][0]['name'] == '変数 色/Frame/Default'
    with tempfile.TemporaryDirectory() as td:
        before, after = Path(td) / 'before.json', Path(td) / 'after.json'
        before.write_text(json.dumps(ka), encoding='utf-8')
        after.write_text(json.dumps(kb), encoding='utf-8')
        assert main(['--before', str(before), '--after', str(after)]) == 1, '作り直しを通した'
        before.write_text(json.dumps(va), encoding='utf-8')
        after.write_text(json.dumps(vb), encoding='utf-8')
        assert main(['--before', str(before), '--after', str(after)]) == 1, '変数の作り直しを通した'
        after.write_text(json.dumps(va), encoding='utf-8')
        assert main(['--before', str(before), '--after', str(after)]) == 0, '変わっていない変数を落とした'
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
        before = json.loads(args.before.read_text(encoding='utf-8'))
        after = json.loads(args.after.read_text(encoding='utf-8'))
        c = [] if _variables_only(before) and _variables_only(after) else changes(before, after)
        refs = references(c, args.references)
        rec, seen = recreated(before, after)
    except (OSError, ValueError, TypeError) as e:
        print(f'改名を照合できません: {e}', file=sys.stderr)
        return 2
    print(json.dumps({'changed': c, 'referenceCandidates': refs, 'recreated': rec}, ensure_ascii=False))
    print('参照候補は文字列で検出します。候補の意味とIDが変わった部品の対応は未検証です')
    if not seen:
        print('**作り直しは見ていません**（どちらかの書き出しに key がありません。2026-11-03 以降の書き出し器で取り直す）')
    if rec:
        print(f'**作り直されたもの {len(rec)} 件**（名前は同じで key が変わった。使う側とのつながりが切れます）:',
              file=sys.stderr)
        for x in rec:
            print(f'  {x["name"]}', file=sys.stderr)
    return 1 if refs or rec else 0


if __name__ == '__main__':
    sys.exit(main())
