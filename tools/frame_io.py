#!/usr/bin/env python3
"""画面をIDで照合し、分割取得を件数・行ハッシュ・全体ハッシュで復元する（#170・#171）。"""
import argparse
import json
import sys
from pathlib import Path
_HERE = str(Path(__file__).resolve().parent)
sys.path.insert(0, _HERE)
try:
    import _utf8  # noqa: F401
finally:
    sys.path.remove(_HERE)   # 読み込んだ側の検索パスを汚さない（#186）


def _harness_sibling(name, folder):
    """ハーネスの兄弟の部品を、**別名で・ファイルの場所から**読む（#186）。

    案件がこの道具を部品として読み込むと、`sys.path` の先頭にハーネスの置き場所が残り、案件の同じ名前の部品
    （aub の design/gen/digest_check.py・FlashEnglish の figma_names.py など）を隠していた。
    `sys.modules` も名前で共有されるので、検索パスを戻すだけでは、先に読まれた案件の部品を拾う。別名なら混ざらない
    """
    import importlib.util
    key = "_harness_" + name
    if key not in sys.modules:
        spec = importlib.util.spec_from_file_location(key, Path(folder) / (name + ".py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[key] = mod
        spec.loader.exec_module(mod)
    return sys.modules[key]


payload_digest = _harness_sibling("digest_check", _HERE).payload_digest


def frame_hash(text):
    # export_frames.jsのh(): UTF-16コード単位の下位バイト。
    h = 0x811c9dc5
    for b in text.encode('utf-16-le', errors='surrogatepass')[::2]:
        h = ((h ^ b) * 0x01000193) & 0xffffffff
    return h


def resolve_frame(frames, reference):
    """IDを優先し、名前が重複する場合は黙って選ばない。"""
    if reference in frames:
        return reference
    ids = [k for k, v in frames.items() if v.get('name') == reference]
    if len(ids) != 1:
        raise ValueError(f'画面 {reference!r} の候補は {len(ids)}件です。IDで指定してください: {ids}')
    return ids[0]


def screen_mapping(frames, mapping, frame_id):
    """生成器が使う対応表をIDで引く。名前への移行期間も取り違えない。"""
    if frame_id not in frames:
        raise ValueError(f'画面IDが書き出しにありません: {frame_id}')
    if frame_id in mapping:
        return mapping[frame_id]
    name = frames[frame_id]['name']
    if name not in mapping:
        raise ValueError(f'対応表に画面がありません: {frame_id} / {name}')
    if resolve_frame(frames, name) != frame_id:
        raise ValueError(f'対応表が別の画面を指しています: {frame_id}')
    return mapping[name]


def merge(manifest, chunks, previous=None):
    if manifest.get('mode') != 'manifest' or not manifest.get('frames'):
        raise ValueError('完全なmanifestがありません')
    result = {}
    mmeta = manifest.get('$meta', {})
    # 「読めなかったもの」: 新しい器は件数とハッシュだけを載せ、本体を notread の断片で返す（#182）。
    # 古い器は manifest と各断片に本体を載せている
    new_style = 'notReadHash' in mmeta
    unseen = [] if new_style else list(mmeta.get('読めなかったもの', []))
    parts = {}
    rows_chunks = []
    for chunk in chunks:
        if new_style and chunk.get('$meta', {}).get('notReadHash') != mmeta['notReadHash']:
            raise ValueError('「読めなかったもの」のハッシュが manifest と違います（別の版か、ONLY_IDS が違う断片）')
        if chunk.get('mode') == 'notread' and new_style:
            for k, item in enumerate(chunk.get('items') or []):
                parts[chunk.get('start', 0) + k] = item
            continue
        if chunk.get('mode') != 'rows' or not chunk.get('frames'):
            raise ValueError('行の断片の形式が違います')
        if set(chunk['frames']) - set(manifest['frames']):
            raise ValueError('manifestに無い画面の断片です')
        rows_chunks.append(chunk)
        if not new_style:
            unseen.extend(chunk.get('$meta', {}).get('読めなかったもの', []))
    if new_style:
        n = mmeta.get('notReadCount', 0)
        missing = [i for i in range(n) if i not in parts]
        if missing or set(parts) - set(range(n)):
            raise ValueError(f'「読めなかったもの」が {n} 件中そろっていません（未取得 {missing[:10]}）。notread モードで取ってください')
        unseen = [parts[i] for i in range(n)]
        if frame_hash(json.dumps(unseen, ensure_ascii=False, separators=(',', ':'))) != mmeta['notReadHash']:
            raise ValueError('「読めなかったもの」のハッシュが合いません')
    chunks = rows_chunks
    for fid, meta in manifest['frames'].items():
        total, hashes = meta['total'], meta['hashes']
        if not isinstance(total, int) or total < 1 or len(hashes) != total:
            raise ValueError(f'{fid}: 行の宣言件数が違います')
        rows = [None] * total
        # ID の一覧（行と同じ順・2026-11-03・#157）。idsHash の無い manifest は古い器なので ID を持たない
        want_ids = 'idsHash' in meta
        ids = [None] * total
        prev = (previous or {}).get('frames', {}).get(fid, {})
        old, old_ids = prev.get('rows', []), prev.get('ids') or []
        for i, row in enumerate(old[:total]):
            if frame_hash(row) == hashes[i]:
                rows[i] = row
                ids[i] = old_ids[i] if i < len(old_ids) else None
        for chunk in chunks:
            part = chunk['frames'].get(fid)
            if part is None:
                continue
            if part['frameHash'] != meta['frameHash']:
                raise ValueError(f'{fid}: 別の版の断片です')
            for index, row in part['rows'].items():
                i = int(index)
                if str(i) != str(index) or i < 0 or i >= total or frame_hash(row) != hashes[i]:
                    raise ValueError(f'{fid}: 行{index}の番号またはハッシュが違います')
                if rows[i] is not None and rows[i] != row:
                    raise ValueError(f'{fid}: 矛盾する行{index}')
                rows[i] = row
                if want_ids:
                    if index not in (part.get('ids') or {}):
                        raise ValueError(f'{fid}: 行{index}の ID がありません（器が古い）')
                    ids[i] = part['ids'][index]
        missing = [i for i, row in enumerate(rows) if row is None]
        if missing:
            raise ValueError(f'{fid}: 未取得の行 {missing}')
        body = json.dumps([meta['section'], meta['name'], rows], ensure_ascii=False, separators=(',', ':'))
        if frame_hash(body) != meta['frameHash']:
            raise ValueError(f'{fid}: 全体ハッシュが違います')
        result[fid] = {'section': meta['section'], 'name': meta['name'], 'rows': rows}
        if want_ids:
            if frame_hash(json.dumps(ids, ensure_ascii=False, separators=(',', ':'))) != meta['idsHash']:
                # 前回から使い回した行は、中身が同じでもノードが作り直されて ID が変わっていることがある
                raise ValueError(f'{fid}: ID の一覧のハッシュが違います。--previous を使わずに全部の行を取り直してください')
            result[fid]['ids'] = ids
    doc = {'frames': result, '$meta': {'読めなかったもの': unseen, 'transferVerified': True,
            'declared': {'screens': len(result)}}}
    doc['$meta']['payloadDigest'] = payload_digest(doc)
    return doc


def self_test():
    rows = ['0|画面|FRAME|300|400|0|0', '1|文字😀|TEXT|10|20|0|0']
    frame = {'name': 'A', 'section': 'S', 'rows': rows}
    body = json.dumps(['S', 'A', rows], ensure_ascii=False, separators=(',', ':'))
    meta = {'name': 'A', 'section': 'S', 'total': 2, 'hashes': [frame_hash(r) for r in rows], 'frameHash': frame_hash(body)}
    manifest = {'mode': 'manifest', 'frames': {'1:1': meta}}
    chunks = [{'mode': 'rows', 'frames': {'1:1': {'frameHash': meta['frameHash'], 'rows': {'0': rows[0], '1': rows[1]}}}}]
    assert merge(manifest, chunks)['frames']['1:1'] == frame
    assert merge(manifest, [], {'frames': {'1:1': frame}})['frames']['1:1'] == frame
    assert resolve_frame({'a': frame, 'b': frame}, 'a') == 'a'
    assert screen_mapping({'a': frame, 'b': frame}, {'a': {'class': 'screen-a'}}, 'a') == {'class': 'screen-a'}
    failures = [lambda: merge(manifest, []),
                lambda: merge(manifest, [{'mode': 'rows', 'frames': {'1:1': {'frameHash': 0, 'rows': {}}}}]),
                lambda: resolve_frame({'a': frame, 'b': frame}, 'A'),
                lambda: screen_mapping({'a': frame, 'b': frame}, {'A': {}}, 'a'),
                lambda: merge(manifest, [{'mode': 'rows', 'frames': {'1:1': {'frameHash': meta['frameHash'], 'rows': {'0': 'broken'}}}}])]
    # ID の一覧（idsHash を持つ manifest）
    ids = ['1:1', ['1:2', '1:3']]
    meta_i = dict(meta, idsHash=frame_hash(json.dumps(ids, ensure_ascii=False, separators=(',', ':'))))
    man_i = {'mode': 'manifest', 'frames': {'1:1': meta_i}}
    ch_i = [{'mode': 'rows', 'frames': {'1:1': {'frameHash': meta['frameHash'], 'rows': {'0': rows[0], '1': rows[1]},
                                               'ids': {'0': ids[0], '1': ids[1]}}}}]
    assert merge(man_i, ch_i)['frames']['1:1'] == dict(frame, ids=ids)
    assert merge(man_i, [], {'frames': {'1:1': dict(frame, ids=ids)}})['frames']['1:1']['ids'] == ids
    # 「読めなかったもの」を notread の断片で分けて取る（#182）
    nr = [{'instance': '1:1', 'fields': ['x'], 'why': 'a'}, {'instance': '1:2', 'fields': ['y'], 'why': 'b'}]
    nmeta = {'notReadCount': 2, 'notReadHash': frame_hash(json.dumps(nr, ensure_ascii=False, separators=(',', ':')))}
    man_n = {'mode': 'manifest', 'frames': {'1:1': meta}, '$meta': nmeta}
    rows_n = [dict(chunks[0], **{'$meta': nmeta})]
    got = merge(man_n, rows_n + [{'mode': 'notread', 'start': 0, 'items': nr[:1], '$meta': nmeta},
                                 {'mode': 'notread', 'start': 1, 'items': nr[1:], '$meta': nmeta}])
    assert got['$meta']['読めなかったもの'] == nr and got['frames']['1:1'] == frame
    failures += [lambda: merge(man_n, rows_n + [{'mode': 'notread', 'start': 0, 'items': nr[:1], '$meta': nmeta}]),  # 欠け
                 lambda: merge(man_n, rows_n + [{'mode': 'notread', 'start': 0, 'items': [nr[1], nr[0]], '$meta': nmeta}]),  # 入れ替わり
                 lambda: merge(man_n, chunks + [{'mode': 'notread', 'start': 0, 'items': nr, '$meta': nmeta}])]  # 別の版の行
    failures += [lambda: merge(man_i, chunks),   # 古い器の断片（ID が無い）
                 lambda: merge(man_i, [], {'frames': {'1:1': dict(frame, ids=['9:9', ids[1]])}}),  # 作り直された節点
                 lambda: merge(man_i, [], {'frames': {'1:1': frame}})]   # 前回に ID が無い
    for fail in failures:
        try:
            fail()
        except ValueError:
            continue
        raise AssertionError('壊した入力が通りました')
    # 案件から部品として読まれても、案件の同じ名前の部品を隠さない（#186）
    import subprocess
    import tempfile as _tf
    with _tf.TemporaryDirectory() as case:
        (Path(case) / 'digest_check.py').write_text("WHO = 'case'\n", encoding='utf-8')
        (Path(case) / 'figma_names.py').write_text("WHO = 'case'\n", encoding='utf-8')
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import digest_check as a; before = list(sys.path);"
                "import importlib.util as u; s = u.spec_from_file_location('frame_io', sys.argv[2]);"
                "m = u.module_from_spec(s); s.loader.exec_module(m);"
                "import digest_check as b, figma_names as c;"
                "print(a.WHO, b.WHO, c.WHO, sys.path == before, callable(m.payload_digest))")
        r = subprocess.run([sys.executable, '-c', code, case, str(Path(__file__).resolve())],
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
        assert r.stdout.split() == ['case', 'case', 'case', 'True', 'True'], \
            f'**案件の同じ名前の部品を隠した、または検索パスを汚した**: {r.stdout} {r.stderr[-300:]}'
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / 'manifest.json'
        p.write_text(json.dumps(manifest), encoding='utf-8')
        assert main([]) == 2
        assert main(['--manifest', str(p)]) == 2
    print('self-test: OK')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--manifest', type=Path)
    ap.add_argument('--chunks', nargs='*', type=Path, default=[])
    ap.add_argument('--previous', type=Path)
    ap.add_argument("--self-test", action='store_true')
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    try:
        read = lambda p: json.loads(p.read_text(encoding='utf-8'))
        if not args.manifest:
            raise ValueError('--manifestが必要です')
        result = merge(read(args.manifest), [read(p) for p in args.chunks], read(args.previous) if args.previous else None)
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f'書き出しを復元できません: {e}', file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
