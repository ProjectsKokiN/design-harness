"""生成器の入出力の基盤。**共有の正本**（2026-09-02 に aub-familywalk から回収）。

それまで案件ごとの複製で、**中身が3倍違っていました**
（aub 9関数・11.8KB / flash-compose 3関数・3.9KB）。
`duplication_check.py` が候補として挙げたものです。

## ここに置くもの

- 書き出しを読む（**宣言した件数と実数を突き合わせる**）
- 生成物を書く（**LF のまま**・変わったかどうかを返す）
- 値の正規化（数値・色）

## ここに置かないもの

**そのデザインシステムの書き出しの形に依存するもの**は案件側に残します
（`variables()` の別名解決・スロットの経路の解釈・効果スタイルの分類など）。
デザインシステムが違えば構造が違うので、共有しても当たりません。

## 使い方（案件の design/gen/export_io.py から）

    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]
                           / 'harness' / 'tools'))
    from gen_io import load, load_raw, number, dart_color, write   # noqa
    gen_io.ROOT = <案件のルート>      # 読み書きの基点を渡す
"""

import json
import pathlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

#: 案件のルート。**入口が差し替える**（既定は呼び出し元の2つ上）。
ROOT = pathlib.Path.cwd()
#: 書き出しの置き場（ROOT からの相対）。
FIGMA_DIR = 'design/figma'


def _figma():
    return pathlib.Path(ROOT) / FIGMA_DIR


def load(name: str) -> dict:
    """書き出しを読み、宣言した件数と実数を突き合わせる。

    **合わなければ生成に進まず落ちる。** 部分読みが黙って通らないようにする。
    """
    path = _figma() / name
    # **無ければ手順を出して止める**（2026-09-02 に flash-compose 版から合流）。
    # aub 版は FileNotFoundError をそのまま投げており、読む側に
    # 「何をすればよいか」が届かなかった
    if not path.exists():
        raise SystemExit(
            f'[NG] 書き出しがありません: {path}\n'
            f'  Figma から書き出し直してください（手順: ~/.claude/skills/'
            f'mobile-harness-setup/references/figma-fullexport.md）。\n'
            f'  レジストリ参照の案件は design-systems を隣にクローンしてください。')
    doc = json.loads(path.read_text(encoding='utf-8'))
    meta = doc.get('$meta', {})
    d = meta.get('declared')
    if d is None:
        raise SystemExit(f'[NG] {name} に $meta.declared がありません。')
    if name == 'variables.json':
        for c in doc['collections']:
            if len(c['variables']) != d[c['name']]:
                raise SystemExit(f'[NG] {name} の {c["name"]}: 宣言 {d[c["name"]]} / 実数 {len(c["variables"])}')
    elif name == 'styles.json':
        for k in ('text', 'paint', 'effect'):
            if len(doc[k]) != d[k]:
                raise SystemExit(f'[NG] {name} の {k}: 宣言 {d[k]} / 実数 {len(doc[k])}')
    elif name == 'component_properties.json':
        got = sum(len(v) for v in doc['components'].values())
        if got != d['rows']:
            raise SystemExit(f'[NG] {name}: 宣言 {d["rows"]} / 実数 {got}')
    elif name == 'hidden_variables.json':
        if len(doc['semanticRefs']) != d['semanticRefs']:
            raise SystemExit(f'[NG] {name}: 宣言 {d["semanticRefs"]} / '
                             f'実数 {len(doc["semanticRefs"])}')
    elif name == 'variable_scopes.json':
        # 規則そのものなので件数は数えない。変数の総数だけ突き合わせる
        pass
    elif name == 'detached.json':
        got = sum(len(v) for v in doc['detached'].values())
        if got != d['rows']:
            raise SystemExit(f'[NG] {name}: 宣言 {d["rows"]} / 実数 {got}')
    elif name == 'default_variants.json':
        if len(doc['sets']) != d['sets']:
            raise SystemExit(f'[NG] {name}: 宣言 {d["sets"]} / 実数 {len(doc["sets"])}')
    elif name == 'descriptions.json':
        got = len(doc['components']) + len(doc['textStyles'])
        if got != d['rows']:
            raise SystemExit(f'[NG] {name}: 宣言 {d["rows"]} / 実数 {got}')
    elif name == 'masks.json':
        got = sum(len(v) for v in doc['masks'].values())
        if got != d['rows']:
            raise SystemExit(f'[NG] {name}: 宣言 {d["rows"]} / 実数 {got}')
    elif name == 'size_limits.json':
        if len(doc['components']) != d['components']:
            raise SystemExit(f'[NG] {name}: 宣言 {d["components"]} / '
                             f'実数 {len(doc["components"])}')
    elif name == 'audit.json':
        if len(doc['fieldNames']) != d['fields']:
            raise SystemExit(f'[NG] {name} の属性名: 宣言 {d["fields"]} / '
                             f'実数 {len(doc["fieldNames"])}')
        got = len(doc['properties']['fills[].type=IMAGE']['rows'])
        if got != d['imageFills']:
            raise SystemExit(f'[NG] {name}: 宣言 {d["imageFills"]} / 実数 {got}')
    elif name == 'child_variants.json':
        got = sum(len(k) for byv in doc['components'].values() for k in byv.values())
        if got != d['rows']:
            raise SystemExit(f'[NG] {name}: 宣言 {d["rows"]} / 実数 {got}')
    elif name == 'constraints.json':
        got = sum(len(v) for v in doc['components'].values())
        if got != d['rows']:
            raise SystemExit(f'[NG] {name}: 宣言 {d["rows"]} / 実数 {got}')
    elif name == 'child_counts.json':
        if len(doc['components']) != d['components']:
            raise SystemExit(f'[NG] {name}: 宣言 {d["components"]} / 実数 {len(doc["components"])}')
    elif name == 'wrap.json':
        if len(doc['components']) != d['components']:
            raise SystemExit(f'[NG] {name}: 宣言 {d["components"]} / 実数 {len(doc["components"])}')
        got = sum(v['variantCount'] for v in doc['components'].values())
        if got != d['variants']:
            raise SystemExit(f'[NG] {name} のバリアント: 宣言 {d["variants"]} / 実数 {got}')
    elif name == 'screen_vectors.json':
        if len(doc['vectors']) != d:
            raise SystemExit(f'[NG] {name}: 宣言 {d} / 実数 {len(doc["vectors"])}')
    elif name == 'components.json':
        if len(doc['componentSets']) != d['componentSets'] or \
           len(doc['singleComponents']) != d['singleComponents']:
            raise SystemExit(f'[NG] {name}: 宣言と実数が違います。')
    else:
        # **知らない書き出しも数える**（2026-09-02 新設）。それまで照合は
        # ファイル名の決め打ちで、**一覧に無い書き出しは宣言があっても
        # 素通り**していた。書き出しが増えるたびにここへ足す前提は、
        # 足し忘れたときに黙る（このハーネスが繰り返し潰してきた形）。
        #
        # 一般の規則: `$meta.declared` の各キーが、同じ名前の
        # トップレベルの入れ物の件数と一致すること。
        if isinstance(d, dict):
            for key, want in d.items():
                v = doc.get(key)
                if not isinstance(v, (dict, list)) or not isinstance(want, int):
                    continue
                if len(v) != want:
                    raise SystemExit(
                        f'[NG] {name} の {key}: 宣言 {want} / 実数 {len(v)}')
    return doc


def load_raw(name: str) -> dict:
    """件数の宣言を持たない書き出し（conflicts.json など）をそのまま読む。"""
    return json.loads((_figma() / name).read_text(encoding='utf-8'))


#: 読めていないプロパティの宣言（tools/gen_notcaptured.py が生成する）
NOTCAPTURED = 'notcaptured.json'


def absent(key: str):
    """そのプロパティが**書き出しに入っていない**なら、理由を返す。入っていれば None。

    2026-09-04 新設（#21）。**「Figma に無い」と「書き出し器が拾っていない」を
    区別できる入口。**

    flash-compose の実測: AI が Figma を読み違えた7件のうち **3件が同じ根**で、
    「書き出しに入っていない情報を、入っていないと知らずに推測で埋めた」だった。
    `itemReverseZIndex` が無いのに `children` の並びだけで重なり順を判断して
    **「Figma が壊れている」と誤報**した（実際は Figma が正しかった）。

    **3件とも「読み直して気づいた」ものは無い。** 無い情報は、無いように
    見えるから。**問える形になっていれば問う。問う先が無いから推測する。**

        if gen_io.absent('itemReverseZIndex'):
            raise SystemExit('重なり順は書き出しに無い。器を直すまで判断しない')

    宣言そのものが無い案件では **SystemExit で止める**。「宣言が無い＝
    読めている」と読むと、この道具は何も見ていないのと同じになる。
    """
    path = _figma() / NOTCAPTURED
    if not path.exists():
        raise SystemExit(
            f'[NG] 読めていないプロパティの宣言がありません: {path}\n'
            f'  **この書き出しが何を読んでいないかを、誰も宣言していません。**\n'
            f'  `python3 <harness>/tools/gen_notcaptured.py --config '
            f'design/notcaptured.json` で作ってください。')
    doc = json.loads(path.read_text(encoding='utf-8'))
    return (doc.get('notCaptured') or {}).get(key)


def number(v) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise SystemExit(f'[NG] 数ではありません: {v!r}')
    return float(v)


def dart_color(hexstr: str) -> str:
    """`#rrggbb` / `#rrggbbaa` → Dart の Color(0xAARRGGBB)。"""
    h = hexstr.lstrip('#')
    if len(h) == 6:
        h += 'ff'
    if len(h) != 8:
        raise SystemExit(f'[NG] 色の形が違います: {hexstr}')
    rr, gg, bb, aa = h[0:2], h[2:4], h[4:6], h[6:8]
    return f'Color(0x{aa}{rr}{gg}{bb})'


def write(path: pathlib.Path, body: str, source: str, gen: str) -> bool:
    """生成物を書く。**変わったかどうかを返す**（べき等性の検査が使う）。"""
    head = (
        '// 自動生成。手で編集しない。\n'
        '//\n'
        f'// 生成元: design/figma/{source}\n'
        f'// 生成器: design/gen/{gen}\n'
        f'// 作り直す: python3 design/gen/{gen}\n'
        '// 検査する: python3 design/gen/verify.py\n'
        '\n'
    )
    text = head + body
    before = path.read_text(encoding='utf-8') if path.exists() else None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    return before != text

def self_test() -> int:
    """落ちるケースを持つ（規律: 検査を足したら落ちるケースを1つ書く）。"""
    import tempfile
    ok = True

    def check(cond, msg):
        nonlocal ok
        if not cond:
            print(f'self-test NG: {msg}'); ok = False

    global ROOT
    keep = ROOT
    with tempfile.TemporaryDirectory() as td:
        ROOT = pathlib.Path(td)
        fig = _figma(); fig.mkdir(parents=True)

        # 宣言と実数が合えば読める
        (fig / 'a.json').write_text(json.dumps(
            {'$meta': {'declared': {'items': 2}}, 'items': {'x': 1, 'y': 2}}),
            encoding='utf-8')  # 一覧に無い名前 → 一般の規則で数える
        try:
            load('a.json'); check(True, '')
        except SystemExit:
            check(False, '宣言と実数が合うのに落ちた')

        # **宣言と実数がずれたら落ちる**（この基盤の本題）
        (fig / 'b.json').write_text(json.dumps(
            {'$meta': {'declared': {'items': 3}}, 'items': {'x': 1}}),
            encoding='utf-8')
        try:
            load('b.json'); check(False, '宣言と実数がずれたのに通した')
        except SystemExit:
            check(True, '')

        # 無いファイルは落ちる
        try:
            load('no_such.json'); check(False, '無いファイルを通した')
        except SystemExit:
            check(True, '')

        # **名前ごとの照合も通す**（2026-09-02）。ここを通さないと、
        # 「宣言と実数がずれても通す」退行が self-test をすり抜ける
        named = {
            'variables.json': (
                {'$meta': {'declared': {'Gap': 2}},
                 'collections': [{'name': 'Gap', 'variables': [1, 2]}]},
                {'$meta': {'declared': {'Gap': 3}},
                 'collections': [{'name': 'Gap', 'variables': [1, 2]}]}),
            'styles.json': (
                {'$meta': {'declared': {'text': 1, 'paint': 0, 'effect': 0}},
                 'text': [{'name': 'A'}], 'paint': [], 'effect': []},
                {'$meta': {'declared': {'text': 2, 'paint': 0, 'effect': 0}},
                 'text': [{'name': 'A'}], 'paint': [], 'effect': []}),
            'components.json': (
                {'$meta': {'declared': {'componentSets': 1, 'singleComponents': 1}},
                 'componentSets': {'A': {}}, 'singleComponents': {'H': {}}},
                {'$meta': {'declared': {'componentSets': 2, 'singleComponents': 1}},
                 'componentSets': {'A': {}}, 'singleComponents': {'H': {}}}),
            'child_counts.json': (
                {'$meta': {'declared': {'components': 1}}, 'components': {'A': 1}},
                {'$meta': {'declared': {'components': 9}}, 'components': {'A': 1}}),
            'screen_vectors.json': (
                {'$meta': {'declared': 1}, 'vectors': {'a': 1}},
                {'$meta': {'declared': 5}, 'vectors': {'a': 1}}),
        }
        for name, (good, bad) in named.items():
            (fig / name).write_text(json.dumps(good), encoding='utf-8')
            try:
                load(name)
            except SystemExit as e:
                check(False, f'{name}: 宣言どおりなのに落ちた（{e}）')
            (fig / name).write_text(json.dumps(bad), encoding='utf-8')
            try:
                load(name); check(False, f'{name}: **宣言と実数がずれたのに通した**')
            except SystemExit:
                pass

        # $meta.declared が無ければ落ちる
        (fig / 'variables.json').write_text(json.dumps({'collections': []}),
                                            encoding='utf-8')
        try:
            load('variables.json'); check(False, '$meta.declared が無いのに通した')
        except SystemExit:
            pass

        # load_raw は宣言を求めない
        (fig / 'raw.json').write_text(json.dumps({'x': 1}), encoding='utf-8')
        try:
            check(load_raw('raw.json') == {'x': 1}, 'load_raw が読めない')
        except SystemExit:
            check(False, 'load_raw が宣言を求めた')

        # 色の変換
        check(dart_color('#ff0000').lower() == 'color(0xffff0000)',
              f'#ff0000 の変換が違う: {dart_color("#ff0000")}')
        check(dart_color('#00ff0080').lower() == 'color(0x8000ff00)',
              f'alpha つきの変換が違う: {dart_color("#00ff0080")}')

        # 書き込みは「変わったか」を返す
        out = pathlib.Path(td) / 'out.dart'
        W = ('variables.json', 'gen_colors.py')
        check(write(out, 'X', *W) is not False, '新規なのに「変わっていない」と言った')
        check(write(out, 'X', *W) is False, '同じ内容なのに「変わった」と言った')
        check(write(out, 'Y', *W) is not False, '違う内容なのに「変わっていない」と言った')
        body = out.read_bytes().decode('utf-8')
        check('\r' not in body, '**CRLF で書いている**（生成物は LF のまま）')
        # **見出しに生成器の申告が入ること。** gen_input_check が
        # 「自動生成と名乗るなら生成器が実在すること」を求めるので、
        # ここで書かないと下流で落ちる（2026-09-02）
        check('自動生成' in body, '見出しに「自動生成」が無い')
        check('生成器: design/gen/gen_colors.py' in body,
              '見出しに生成器の申告が無い（gen_input_check が落とす）')
    ROOT = keep
    # ── 件数の照合が、書き出しの種類ごとに本当に落ちるか ──────────────
    # ここが load() の要点。**通っていない分岐があると、その種類の書き出しは
    # 件数が合わなくても黙って通る。**
    def 落ちるか(name, doc):
        with tempfile.TemporaryDirectory() as td:
            fd = pathlib.Path(td) / FIGMA_DIR
            fd.mkdir(parents=True)
            (fd / name).write_text(json.dumps(doc, ensure_ascii=False), encoding='utf-8')
            keep = globals()['ROOT']
            globals()['ROOT'] = pathlib.Path(td)
            try:
                load(name)
                return False
            except SystemExit:
                return True
            finally:
                globals()['ROOT'] = keep

    種類 = [
        ('variables.json',
         {'$meta': {'declared': {'Color': 2}},
          'collections': [{'name': 'Color', 'variables': [1]}]}),
        ('styles.json',
         {'$meta': {'declared': {'text': 2, 'paint': 0, 'effect': 0}},
          'text': [1], 'paint': [], 'effect': []}),
        ('component_properties.json',
         {'$meta': {'declared': {'rows': 3}}, 'components': {'A': [1]}}),
        ('hidden_variables.json',
         {'$meta': {'declared': {'semanticRefs': 2}}, 'semanticRefs': [1]}),
        ('detached.json',
         {'$meta': {'declared': {'rows': 2}}, 'detached': {'A': [1]}}),
        ('variant_holes.json',
         {'$meta': {'declared': {'sets': 2}}, 'sets': [1]}),
        ('descriptions.json',
         {'$meta': {'declared': {'rows': 3}}, 'components': [1], 'textStyles': [1]}),
        ('masks.json',
         {'$meta': {'declared': {'rows': 2}}, 'masks': {'A': [1]}}),
        ('components.json',
         {'$meta': {'declared': {'components': 2, 'variants': 0}},
          'components': {'A': {'variantCount': 0}}}),
    ]
    落ちなかった = []
    for name, doc in 種類:
        try:
            if not 落ちるか(name, doc):
                落ちなかった.append(name)
        except (KeyError, TypeError):
            pass          # その分岐が別の形を期待している。ここでは問わない
    check(not 落ちなかった,
          f"**件数が合わないのに通る書き出しがあります**: {落ちなかった}")

    check(落ちるか('よその書き出し.json',
                 {'$meta': {'declared': {'rows': 2}}, 'rows': [1]}),
          "**専用の分岐が無い書き出しで、件数の食い違いを見逃す**")
    check(落ちるか('no_meta.json', {'rows': [1]}),
          "**$meta.declared が無いのに通る**")

    with tempfile.TemporaryDirectory() as td:
        keep = globals()['ROOT']; globals()['ROOT'] = pathlib.Path(td)
        try:
            load('無い.json'); check(False, "無い書き出しで落ちない")
        except SystemExit as e:
            check('figma-fullexport' in str(e),
                  "**書き出しが無いときに、取り直す手順を出していない**")
        finally:
            globals()['ROOT'] = keep

    # ── number / dart_color の落ちるケース ────────────────────────────
    for 悪い in (True, False, '12', None, [1]):
        try:
            number(悪い); check(False, f"**数でないものを通した: {悪い!r}**")
        except SystemExit:
            pass
    check(number(3) == 3.0 and number(1.5) == 1.5, "数を数として返さない")

    for 悪い in ('#12345', '#1234567', 'zz', ''):
        try:
            dart_color(悪い); check(False, f"**色の形が違うのに通した: {悪い!r}**")
        except SystemExit:
            pass
    check(dart_color('#ff5800') == 'Color(0xffff5800)', "6桁の色が違う")
    check(dart_color('#ff580080') == 'Color(0x80ff5800)', "8桁の色が違う")

    # ── load_raw は件数を見ない（見たら別物になる）────────────────────
    with tempfile.TemporaryDirectory() as td:
        fd = pathlib.Path(td) / FIGMA_DIR; fd.mkdir(parents=True)
        (fd / 'conflicts.json').write_text('{"a": 1}', encoding='utf-8')
        keep = globals()['ROOT']; globals()['ROOT'] = pathlib.Path(td)
        try:
            check(load_raw('conflicts.json') == {'a': 1}, "load_raw が読めない")
        finally:
            globals()['ROOT'] = keep

    # ── absent(): 読めていないプロパティを問える（#21）─────────────────
    with tempfile.TemporaryDirectory() as td:
        fd = pathlib.Path(td) / FIGMA_DIR; fd.mkdir(parents=True)
        keep = globals()['ROOT']; globals()['ROOT'] = pathlib.Path(td)
        try:
            nc = fd / NOTCAPTURED
            nc.write_text(json.dumps({"notCaptured": {
                "itemReverseZIndex": "キャンバススタッキング。children の並びだけで"
                                     "重なり順を判断しないこと"}}, ensure_ascii=False),
                encoding='utf-8')
            check('重なり順' in (absent('itemReverseZIndex') or ''),
                  'absent() が理由を返さない')
            check(absent('layoutMode') is None,
                  'absent() が読めているキーに理由を返した')
            # **宣言が無ければ止まる。** 「宣言が無い＝読めている」と読ませない
            nc.unlink()
            try:
                absent('itemReverseZIndex')
                check(False, '宣言が無いのに absent() が答えた')
            except SystemExit:
                pass
        finally:
            globals()['ROOT'] = keep

    print('self-test:', 'OK' if ok else 'NG')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(self_test())
