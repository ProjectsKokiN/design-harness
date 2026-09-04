#!/usr/bin/env python3
"""Figma が書き出しより新しくなっていないかを見る（鮮度の検査・テンプレート）。

【テンプレートについて】flash-compose の実運用版のコピー（2026-08-28 回収）。
「案件ごとに埋める」の3定数だけを具体化して <プロジェクト>/design/figma_freshness.py に置く（3定数を埋めるためコピーが要る唯一の道具）。
本番リリースの合格条件4（鮮度）はこれで測る（references/production-gate.md）。
figma-fullexport.md が「Figma を触る作業の前に必ず回す」と書いていながら、
テンプレが無く新規案件に配られていなかった（2026-08-28 の監査での是正）。

**「Figma が変わった」をユーザーに言われて初めて気づく状態をやめるため**
（2026-08-21）。ボトムナビの色3件は、Figma で直された後もこちらは古い値の
まま生成していて、指摘されるまで分かりませんでした。

    source ~/.claude/.env            # FIGMA_TOKEN を読む
    python3 design/figma_freshness.py           # 変わったセットを名指しする
    python3 design/figma_freshness.py --update  # 書き出しを取り直した後に指紋を更新

## 仕組み

書き出し（`../design-systems/414/figma/components.json`）は Plugin API で
作りますが、**この検査は REST API だけで完結させます**。プラグインと REST の
値の差でぬか喜び・空振りを起こさないため、比べるのは
「REST で読んだ指紋」対「REST で読んで保存した指紋」です。

指紋に入れる項目（[DIGEST_FIELDS]）は**色と余白と並び**に絞ります。
座標のような、Figma で並べ替えるだけで動く値は入れません。
"""

import hashlib
import contextlib
import io
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

ROOT = Path(__file__).resolve().parent.parent

# ---- 案件ごとに埋める（3つだけ）--------------------------------------------
#: 全量書き出しの components.json。レジストリ参照の案件はレジストリ側を指す
EXPORT = ROOT / '{{書き出しのパス。例: ../design-systems/<名前>/figma/components.json}}'
FILE_KEY = '{{Figma の fileKey}}'
#: 参照しないページ（書き出しと同じ。同名の component set を拾わないため）。
#: **PAGE_SCOPE があればそちらが優先。** 除外方式は残しているが弱い（下記）
SKIP_PAGES = ['{{下書きページ名}}', '{{AI出力ページ名}}']

#: 参照してよいページの宣言（`design/figma/page-scope.json` の `allowed`）。
#: **許可リスト方式**。2026-09-02 に aub-familywalk から回収した。
#:
#: 除外方式（SKIP_PAGES）だと **Figma に新しいページが増えたとき黙って対象に入る**。
#: しかも書き出し器は許可リスト方式なので、**器と鮮度検査が別のページを見る**状態に
#: なる（2026-09-02 に flash-compose で実際に起きた: 器は
#: ⚙️_Styles&Components だけ、鮮度は Sandbox / AI Output 以外の全ページ）。
#:
#: 案件の入口（シム）で `PAGE_SCOPE = Path(...)` を差し込む。無ければ
#: SKIP_PAGES に落ちるが、**弱い方式であることを毎回表示する。**
PAGE_SCOPE = None

#: スタイルの鮮度を見るための書き出し（2026-09-02 に aub から回収）。
#: 両方そろっているときだけスタイルを見る。無ければ component set だけを見て、
#: **見ていないことを表示する**（黙って飛ばさない）。
STYLES_EXPORT = None
DESCS_EXPORT = None
# ---------------------------------------------------------------------------

#: 指紋に入れる項目。**並べ替えで動く値（座標）は入れない。**
DIGEST_FIELDS = [
    'itemSpacing', 'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft',
    'layoutMode', 'primaryAxisAlignItems', 'counterAxisAlignItems',
    'layoutSizingHorizontal', 'layoutSizingVertical',
    'textAlignHorizontal', 'textAlignVertical', 'layoutGrow', 'layoutAlign',
]


def get(url: str) -> dict:
    token = os.environ.get('FIGMA_TOKEN')
    if not token:
        print('FIGMA_TOKEN がありません。`source ~/.claude/.env` を先に実行してください',
              file=sys.stderr)
        raise SystemExit(2)
    req = urllib.request.Request(url, headers={'X-Figma-Token': token})
    return json.load(urllib.request.urlopen(req))


def node_digest(n: dict, names: dict | None = None) -> str:
    """1ノードぶんの指紋のもと。子は名前と型と指紋の並びだけ見る。

    **id ではなく名前で指紋を作ります**（2026-08-22 の監査での是正）。
    それまで色は変数の id、スタイルはスタイルの id で指紋にしていたため、
    **改名だけが起きたときに動きませんでした**（書き出しは名前を保存するので、
    書き出しの中身は間違いになるのに検査は黙って通る）。
    実際にレジストリの履歴に「エフェクトの改名を取り込む」があります。

    [names] は `id → 名前` の対応。スタイル名は REST の応答に入っています。
    変数名は `design/figma-raw/_varmap.json`（プラグインで取った対応表）から
    引きます。**対応表に無い id は id のまま指紋に入れます**（新しい変数が
    増えたときは指紋が動くので、それで気づけます）。
    """
    names = names or {}
    parts = [n.get('name', ''), n['type']]
    for k in DIGEST_FIELDS:
        v = n.get(k, (n.get('style') or {}).get(k))
        if v is not None:
            parts.append(f'{k}={v}')
    for key in ('fills', 'strokes'):
        for pnt in (n.get(key) or []):
            bv = (pnt.get('boundVariables') or {}).get('color') or {}
            vid = bv.get('id')
            ref = names.get(vid, vid) if vid else pnt.get('color')
            parts.append(f'{key}={ref}')
    for k, sid in (n.get('styles') or {}).items():
        parts.append(f'style:{k}={names.get(sid, sid)}')
    box = n.get('absoluteBoundingBox') or {}
    if 'width' in box:
        parts.append(f'wh={round(box["width"])}x{round(box["height"])}')
    for c in (n.get('children') or []):
        parts.append(node_digest(c, names))
    return hashlib.sha256('|'.join(map(str, parts)).encode()).hexdigest()[:12]


def pages_of(doc) -> tuple[list, str]:
    """参照するページと、その選び方の説明を返す。

    **許可リスト方式が本命。** PAGE_SCOPE があればそれを使う。
    無ければ SKIP_PAGES に落ちるが、弱い方式であることを毎回言う。
    """
    if PAGE_SCOPE is not None and Path(PAGE_SCOPE).exists():
        allow = json.loads(Path(PAGE_SCOPE).read_text(encoding='utf-8'))['allowed']
        pages = [p for p in doc['children'] if p['name'] in allow]
        if not pages:
            print(f'許可されたページが1枚も見つかりません: {allow}\n'
                  f'  Figma のページ: {[p["name"] for p in doc["children"]]}\n'
                  f'  **空のまま進めると「Figma が空」に見えます。**', file=sys.stderr)
            raise SystemExit(2)
        return pages, f'許可リスト {allow}'
    pages = [p for p in doc['children'] if p['name'] not in SKIP_PAGES]
    return pages, (f'除外リスト {SKIP_PAGES}（**弱い方式**。Figma に新しいページが'
                   f'増えたとき黙って対象に入る。page-scope.json を作って'
                   f'PAGE_SCOPE を差し込むと許可リストになる）')


def read_sets() -> dict:
    """参照するページの component set を name → 指紋 で返す。"""
    doc = get(f'https://api.figma.com/v1/files/{FILE_KEY}?depth=1')['document']
    pages, how = pages_of(doc)
    print(f'ページの選び方: {how}')
    ids = ','.join(p['id'] for p in pages)
    data = get(f'https://api.figma.com/v1/files/{FILE_KEY}/nodes?ids={ids}')
    found: dict[str, str] = {}
    dup: list[str] = []

    def walk(n, names, in_set=False):
        # 単体の COMPONENT も読む（planttalk 2026-08-28: COMPONENT_SET しか
        # 読まなかったため、Header / Footer など「全画面に出るのに単体」の部品が
        # 鮮度の対象外だった。414 に単体が0件だったため露出していなかった）。
        # COMPONENT_SET の子（バリアント）は親の指紋に含まれるので数えない。
        if n['type'] == 'COMPONENT_SET' or (n['type'] == 'COMPONENT' and not in_set):
            name = n['name']
            if name in found:
                dup.append(name)
            found[name] = node_digest(n, names)
            if n['type'] == 'COMPONENT_SET':
                return
            in_set = True   # COMPONENT の中に COMPONENT は無いが、念のため
        for c in (n.get('children') or []):
            walk(c, names, in_set or n['type'] == 'COMPONENT_SET')

    # **id → 名前の対応表。** スタイル名は REST の応答に入っている。
    # 変数名はプラグインで取った対応表（_varmap.json）から引く。
    names: dict[str, str] = {}
    varmap = ROOT / 'design' / 'figma-raw' / '_varmap.json'
    if varmap.exists():
        names.update(json.loads(varmap.read_text(encoding='utf-8'))['map'])
    for nid, entry in data['nodes'].items():
        for sid, meta in (entry.get('styles') or {}).items():
            if isinstance(meta, dict) and meta.get('name'):
                names[sid] = meta['name']
    for nid, entry in data['nodes'].items():
        walk(entry['document'], names)
    if dup:
        print(f'同名の component set が2つ以上あります: {sorted(set(dup))}\n'
              '  どちらが正かは機械で決められません。**止めます。**', file=sys.stderr)
        raise SystemExit(2)
    return found


def read_styles() -> dict | None:
    """**そのページで使われている**スタイルを 名前 → (種類, 説明) で返す。

    2026-09-02 に aub-familywalk から回収した。

    REST の nodes 応答に入るのは「実際に当たっているスタイル」だけで、
    ファイルにある全量ではない（aub の実測: 42 件のうち 18 件）。
    **値も読めない。** それでも名前と説明のずれは拾える。
    全量と値は Plugin API 側（書き出し器）で見る。

    STYLES_EXPORT / DESCS_EXPORT がそろっていなければ None（見ない）。
    """
    if not (STYLES_EXPORT and DESCS_EXPORT
            and Path(STYLES_EXPORT).exists() and Path(DESCS_EXPORT).exists()):
        return None
    doc = get(f'https://api.figma.com/v1/files/{FILE_KEY}?depth=1')['document']
    pages, _ = pages_of(doc)
    ids = ','.join(p['id'] for p in pages)
    data = get(f'https://api.figma.com/v1/files/{FILE_KEY}/nodes?ids={ids}')
    out = {}
    for _, entry in data['nodes'].items():
        for _sid, meta in (entry.get('styles') or {}).items():
            if isinstance(meta, dict) and meta.get('name'):
                out[meta['name']] = (meta.get('styleType'),
                                     (meta.get('description') or '').strip())
    return out


def compare_styles(now: dict) -> list[str]:
    """スタイルの名前と説明のずれを返す。**値は見ない。**"""
    ng = []
    styles = json.loads(Path(STYLES_EXPORT).read_text(encoding='utf-8'))
    descs = json.loads(Path(DESCS_EXPORT).read_text(encoding='utf-8'))
    kind = {'TEXT': 'text', 'FILL': 'paint', 'EFFECT': 'effect'}
    aru = {k: {x['name'] for x in styles.get(k, [])}
           for k in ('text', 'paint', 'effect')}
    for name, (style_type, desc) in sorted(now.items()):
        k = kind.get(style_type)
        if k is None:
            ng.append(f'知らないスタイルの種類です: {style_type}（{name}）')
            continue
        if name not in aru[k]:
            ng.append(f'Figma で使われている {k} スタイル「{name}」が書き出しにありません')
            continue
        if k == 'text':
            kaita = (descs.get('textStyles') or {}).get(name, '')
            if desc != kaita:
                ng.append(f'{name} の説明が違います: Figma「{desc}」/ 書き出し「{kaita}」')
    return ng


def body_hash(doc: dict) -> str:
    """書き出し本体（componentSets）の指紋。

    **なぜ要るか**（2026-08-21 の監査）: `--update` は `restDigests` を今の
    Figma で上書きするだけで、書き出し本体を読みも比べもしていませんでした。
    そのため **Plugin API の取り直しを忘れて `--update` を先に打つ**と、以後の
    検査は永久に緑になり、表示は「Figma は書き出しと同じです」と断言します。
    本体の指紋を並べて持ち、「Figma は動いたのに本体は動いていない」を拒みます。
    """
    # **単体 component も入れる**（2026-09-02 に aub から回収）。componentSets
    # だけを掛けていたので、Header / Footer / BottomNavigation / EmptyStates を
    # 取り直しても本体の指紋が動かなかった——つまり「取り直し忘れの拒否」が
    # その4件については働いていなかった
    body = json.dumps({'componentSets': doc['componentSets'],
                       'singleComponents': doc.get('singleComponents') or {}},
                      ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()[:12]


def compare(saved: dict, now: dict, exported: set, excluded: set) -> dict:
    """**名前のずれと値のずれを別々に返す純粋関数。**

    切り出した理由（2026-08-21）: 名前の食い違いを報告した時点で `return 1` して
    いたため、**同じ回に変わっていた値を一度も比べていませんでした**。
    Waveform が増えた件で止まり、トグルのエフェクトスタイルの変更
    （Selected=True が `InnerShadow/Neutral/Subtle` へ）を検出できず、
    ユーザー指摘で気づいた。名前と値は別の話なので、両方を必ず出す。

    網（REST API）に触らないので `--selftest` で仕組みごと検査できる。
    """
    return {
        'onlyFigma': sorted(set(now) - exported),
        'onlyExport': sorted(exported - excluded - set(now)),
        'added': sorted(set(now) - set(saved)),
        'removed': sorted(set(saved) - set(now)),
        'changed': sorted(k for k in now if k in saved and now[k] != saved[k]),
    }


def self_test() -> int:
    """網に触らずに [compare] の振る舞いを確かめる。"""

    import os
    import tempfile
    cases = []

    # 本題の退行: 名前がずれていても値のずれを隠さない
    r = compare(
        saved={'A': 'aaa', 'B': 'bbb'},
        now={'A': 'aaa', 'B': 'ZZZ', 'C': 'ccc'},
        exported={'A', 'B'},
        excluded=set(),
    )
    cases.append(('名前のずれが値のずれを隠さない',
                  r['onlyFigma'] == ['C'] and r['changed'] == ['B']))

    # 除外を宣言したセットは名前のずれに数えない（両側とも）
    r = compare(saved={'A': 'aaa'}, now={'A': 'aaa', 'Icons': 'x'},
                exported={'A', 'Icons'}, excluded={'Icons'})
    cases.append(('excluded は Figma 側のずれに数えない', r['onlyFigma'] == []))
    cases.append(('excluded は書き出し側のずれにも数えない',
                  r['onlyExport'] == []))

    # 消えたセットは removed と onlyExport の両方で分かる
    r = compare(saved={'A': 'aaa', 'B': 'bbb'}, now={'A': 'aaa'},
                exported={'A', 'B'}, excluded=set())
    cases.append(('消えたセットが両方に出る',
                  r['removed'] == ['B'] and r['onlyExport'] == ['B']))

    # **main() の配線も見る。** compare の答えの形だけを見ていると、
    # main が名前のずれで早期 return する形に戻っても selftest は通ります
    # （2026-08-21 の監査での指摘。まさに今回直した退行がすり抜ける）。
    src = Path(__file__).read_text(encoding='utf-8')
    body = src[src.index('def main('):]
    cases.append((
        'main が名前のずれで打ち切らない',
        'name_drift = True' in body and 'if not update:\n            return 1' not in body,
    ))
    cases.append((
        'main が名前と値の両方を出す',
        "d['added']" in body or 'd["added"]' in body,
    ))

    # --- 純粋な関数を実際に動かす（2026-09-02 新設）--------------------------
    # それまで self-test は `compare()` の1行しか通っておらず（実測 1/203 行）、
    # **main() の配線は「ソースを grep」して確かめていた**——コードが
    # そう見えるかを見ており、そう動くかは見ていなかった。
    # **条件4 の道具としては薄すぎる。**
    import tempfile as _tf

    # node_digest: 同じ木なら同じ値・1つ変えたら変わる
    n1 = {'name': 'A', 'type': 'FRAME', 'itemSpacing': 8,
          'children': [{'name': 'T', 'type': 'TEXT', 'children': []}]}
    n2 = json.loads(json.dumps(n1)); n2['itemSpacing'] = 12
    n3 = json.loads(json.dumps(n1)); n3['children'][0]['name'] = 'U'
    cases.append(('node_digest: 同じ木なら同じ値',
                  node_digest(n1) == node_digest(json.loads(json.dumps(n1)))))
    cases.append(('node_digest: 余白を変えたら変わる', node_digest(n1) != node_digest(n2)))
    cases.append(('node_digest: **子の名前を変えても変わる**',
                  node_digest(n1) != node_digest(n3)))

    # body_hash: componentSets が変われば変わる
    d1 = {'componentSets': {'A': {'x': 1}}}
    d2 = {'componentSets': {'A': {'x': 2}}}
    cases.append(('body_hash: 本体が変われば変わる', body_hash(d1) != body_hash(d2)))
    cases.append(('body_hash: 同じなら同じ', body_hash(d1) == body_hash(
        {'componentSets': {'A': {'x': 1}}})))

    # pages_of: 許可リストが除外リストより優先する
    doc = {'children': [{'id': '1', 'name': 'Sandbox'}, {'id': '2', 'name': 'Comp'},
                        {'id': '3', 'name': 'New'}]}
    g = globals()
    keep = (g['PAGE_SCOPE'], g['SKIP_PAGES'])
    with _tf.TemporaryDirectory() as td:
        scope = Path(td) / 'page-scope.json'
        scope.write_text(json.dumps({'allowed': ['Comp']}), encoding='utf-8')
        g['SKIP_PAGES'] = ['Sandbox']
        g['PAGE_SCOPE'] = None
        pages, how = pages_of(doc)
        cases.append(('除外リストだと**新しいページが黙って入る**',
                      {p['name'] for p in pages} == {'Comp', 'New'} and '弱い' in how))
        g['PAGE_SCOPE'] = scope
        pages, how = pages_of(doc)
        cases.append(('許可リストなら宣言したページだけ',
                      {p['name'] for p in pages} == {'Comp'} and '許可' in how))
        scope.write_text(json.dumps({'allowed': ['NoSuchPage']}), encoding='utf-8')
        try:
            pages_of(doc)
            cases.append(('許可ページが0枚なら止まる', False))
        except SystemExit:
            cases.append(('許可ページが0枚なら止まる', True))

        # compare_styles: 名前の欠落・説明のずれ・知らない種類
        g['STYLES_EXPORT'] = Path(td) / 'styles.json'
        g['DESCS_EXPORT'] = Path(td) / 'descriptions.json'
        g['STYLES_EXPORT'].write_text(json.dumps(
            {'text': [{'name': 'Body/M'}], 'paint': [], 'effect': []}),
            encoding='utf-8')
        g['DESCS_EXPORT'].write_text(json.dumps(
            {'textStyles': {'Body/M': '本文'}}), encoding='utf-8')
        cases.append(('スタイルが一致すれば何も出ない',
                      compare_styles({'Body/M': ('TEXT', '本文')}) == []))
        cases.append(('**説明のずれを拾う**',
                      len(compare_styles({'Body/M': ('TEXT', '違う説明')})) == 1))
        cases.append(('書き出しに無いスタイルを拾う',
                      len(compare_styles({'Title/L': ('TEXT', '')})) == 1))
        cases.append(('知らない種類を拾う',
                      len(compare_styles({'X': ('SHADOW', '')})) == 1))
        # 設定が無ければスタイルは見ない（黙って通さず None を返す）
        g['STYLES_EXPORT'] = None
        cases.append(('設定が無ければスタイルを見ない（None）', read_styles() is None))
    g['PAGE_SCOPE'], g['SKIP_PAGES'] = keep
    g['STYLES_EXPORT'] = g['DESCS_EXPORT'] = None

    # --- main() を**網に触らず実際に動かす**（2026-09-02 新設）---------------
    # それまで main の配線は「ソースを grep」して確かめており、そう動くかは
    # 見ていなかった。get() を差し替えれば網なしで全経路を通せる。
    with _tf.TemporaryDirectory() as td:
        d = Path(td)
        SETS = {'Buttons': {'type': 'COMPONENT_SET', 'name': 'Buttons',
                            'itemSpacing': 8, 'children': []},
                'Header': {'type': 'COMPONENT', 'name': 'Header',
                           'itemSpacing': 4, 'children': []}}

        def fake_get(url, _sets=SETS):
            if 'depth=1' in url:
                return {'document': {'children': [{'id': '1', 'name': 'Comp'}]}}
            return {'nodes': {'1': {'styles': {},
                                    'document': {'type': 'CANVAS', 'name': 'Comp',
                                                 'children': list(_sets.values())}}}}

        def run_main(export_doc, sets=None, argv=('x',)):
            (d / 'export.json').write_text(json.dumps(export_doc), encoding='utf-8')
            g2 = globals()
            keep2 = (g2['EXPORT'], g2['get'], g2['PAGE_SCOPE'], g2['SKIP_PAGES'],
                     sys.argv)
            g2['EXPORT'] = d / 'export.json'
            g2['SKIP_PAGES'] = []
            g2['PAGE_SCOPE'] = None
            g2['get'] = (lambda u: fake_get(u, sets)) if sets else fake_get
            sys.argv = list(argv)
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    return main()
            finally:
                (g2['EXPORT'], g2['get'], g2['PAGE_SCOPE'], g2['SKIP_PAGES'],
                 sys.argv) = keep2

        # いまの Figma で指紋を作り、それを書き出しに入れれば「同じ」になる
        g3 = globals()
        keep3 = (g3['get'], g3['SKIP_PAGES'], g3['PAGE_SCOPE'])
        g3['get'], g3['SKIP_PAGES'], g3['PAGE_SCOPE'] = fake_get, [], None
        now = read_sets()
        g3['get'], g3['SKIP_PAGES'], g3['PAGE_SCOPE'] = keep3

        base = {'$meta': {'restDigests': dict(now)},
                'componentSets': {'Buttons': {}, 'Header': {}}}
        cases.append(('main: Figma と書き出しが同じなら 0', run_main(base) == 0))

        # **単体 component を書き出し側に数える**（2026-09-02 に aub から回収）。
        # componentSets だけを見ていたため、書き出しにある Header が
        # 「Figma にしか無い」と報告されていた
        split = {'$meta': {'restDigests': dict(now)},
                 'componentSets': {'Buttons': {}},
                 'singleComponents': {'Header': {}}}
        cases.append(('main: 単体は singleComponents に入っていてもよい',
                      run_main(split) == 0))

        # body_hash が単体の変化でも動くこと（取り直し忘れの拒否が効く）
        cases.append(('body_hash: 単体が変われば動く',
                      body_hash({'componentSets': {}, 'singleComponents': {'H': 1}})
                      != body_hash({'componentSets': {}, 'singleComponents': {'H': 2}})))

        # **単体 COMPONENT も指紋の対象**（planttalk が 2026-08-28 に直した退行）
        cases.append(('main: 単体 COMPONENT も見ている', 'Header' in now))

        # 値が変わったら 1
        moved = json.loads(json.dumps(SETS)); moved['Buttons']['itemSpacing'] = 99
        cases.append(('main: 値が変わったら 1', run_main(base, moved) == 1))

        # **名前のずれで打ち切らず、値のずれも出す**（2026-08-21 の退行）
        base2 = {'$meta': {'restDigests': dict(now)},
                 'componentSets': {'Buttons': {}}}          # Header が書き出しに無い
        cases.append(('main: 名前のずれがあっても値を比べる',
                      run_main(base2, moved) == 1))

        # 書き出しが空でも「同じ」と言わない
        cases.append(('main: 書き出しに無いセットがあれば 1',
                      run_main({'$meta': {'restDigests': {}},
                                'componentSets': {}}) == 1))

    ng = [name for name, ok in cases if not ok]
    # ── read_styles: **網に触らず**通す（ここが一番大きい未通過の塊）──────
    g4 = globals()
    keep4 = {k: g4.get(k) for k in ('get', 'STYLES_EXPORT', 'DESCS_EXPORT',
                                    'SKIP_PAGES', 'PAGE_SCOPE', 'FILE_KEY')}
    try:
        with tempfile.TemporaryDirectory() as td:
            se = Path(td) / 's.json'; de = Path(td) / 'd.json'
            se.write_text('{}', encoding='utf-8'); de.write_text('{}', encoding='utf-8')

            def styles_get(url):
                if 'depth=1' in url:
                    return {'document': {'children': [
                        {'id': '1:1', 'name': 'Comp', 'type': 'CANVAS'}]}}
                return {'nodes': {'1:1': {'styles': {
                    's1': {'name': 'Text/Body', 'styleType': 'TEXT',
                           'description': '  本文  '},
                    's2': {'name': 'Paint/Bg', 'styleType': 'FILL'},
                    's3': {'noName': True},          # 名前が無いものは落とす
                }}}}

            g4['get'] = styles_get
            g4['FILE_KEY'] = 'K'
            g4['SKIP_PAGES'] = []
            g4['PAGE_SCOPE'] = None

            # そろっていなければ **見ない**（None）
            g4['STYLES_EXPORT'] = None; g4['DESCS_EXPORT'] = None
            cases.append(('設定が無いのに読みに行った', read_styles() is None))
            g4['STYLES_EXPORT'] = str(se); g4['DESCS_EXPORT'] = str(Path(td) / 'ない.json')
            cases.append(('**片方が無いのに読みに行った**', read_styles() is None))

            g4['DESCS_EXPORT'] = str(de)
            got = read_styles()
            cases.append(('そろっているのに読まない', got is not None))
            cases.append((f'**説明の前後の空白を落としていない**: {got.get("Text/Body")!r}', got.get('Text/Body') == ('TEXT', '本文')))
            cases.append(('説明が無いスタイルを落とした', got.get('Paint/Bg') == ('FILL', '')))
            cases.append((f'**名前の無いスタイルを拾っている**: {sorted(got)}', len(got) == 2))
    finally:
        for k, v in keep4.items():
            g4[k] = v

    # ── get: トークンが無ければ **手順を出して** 落ちる ────────────────
    keep_tok = os.environ.pop('FIGMA_TOKEN', None)
    try:
        get('https://api.figma.com/v1/files/K')
        cases.append(('**FIGMA_TOKEN が無いのに読みに行った**', False))
    except SystemExit as e:
        cases.append((f'トークン無しの終了コードが 2 でない（{e.code}）', e.code == 2))
    finally:
        if keep_tok is not None:
            os.environ['FIGMA_TOKEN'] = keep_tok

    print(f'[figma_freshness] selftest {len(cases) - len(ng)}/{len(cases)} 件パス')
    for name in ng:
        print(f'  NG: {name}', file=sys.stderr)
    return 1 if ng else 0


#: 旧名。案件の入口が `selftest()` を呼んでいる場合のため残す（2026-09-02）。
#: 他の道具は self_test / --self-test なので、そちらへそろえた
#: （名前が違うせいで stage_check の網羅の測定から漏れていた）
selftest = self_test


def load_config(path) -> None:
    """設定ファイルから案件固有の値を入れる（2026-09-02 新設）。

    それまで案件の入口は**テンプレートのソースを文字列置換**して動かしていた。
    テンプレートの1行を直すと入口が黙って壊れる形なので、設定で渡せるようにした。
    **旧方式の入口はそのまま動く**（モジュール変数を直に差し替えているため）。

        {
          "export": "../design-systems/<名前>/figma/components.json",
          "fileKey": "...",
          "pageScope": "design/figma/page-scope.json",
          "stylesExport": "design/figma/styles.json",
          "descsExport": "design/figma/descriptions.json"
        }
    """
    g = globals()
    conf = json.loads(Path(path).read_text(encoding='utf-8'))
    base = Path(path).resolve().parent
    if conf.get('export'):
        g['EXPORT'] = (base / conf['export']).resolve()
    if conf.get('fileKey'):
        g['FILE_KEY'] = conf['fileKey']
    if conf.get('skipPages') is not None:
        g['SKIP_PAGES'] = conf['skipPages']
    for key, var in (('pageScope', 'PAGE_SCOPE'), ('stylesExport', 'STYLES_EXPORT'),
                     ('descsExport', 'DESCS_EXPORT')):
        if conf.get(key):
            g[var] = (base / conf[key]).resolve()
    for var, label in (('EXPORT', 'export'), ('FILE_KEY', 'fileKey')):
        v = str(g[var])
        if '{{' in v:
            print(f'設定に {label} がありません（テンプレートのままです）: {v}',
                  file=sys.stderr)
            raise SystemExit(2)


def main() -> int:
    if '--selftest' in sys.argv or '--self-test' in sys.argv:
        return self_test()
    if '--config' in sys.argv:
        load_config(sys.argv[sys.argv.index('--config') + 1])
    update = '--update' in sys.argv
    doc = json.loads(EXPORT.read_text(encoding='utf-8'))
    saved = (doc['$meta'].get('restDigests') or {})
    now = read_sets()

    # **名前の照合を先にする。** 指紋だけ見ていると「書き出しに無いセット」を
    # 見落とす（2026-08-21 実測: 初回の実行で Slider が書き出しに無く、
    # ProgressCircular / ProgressLinear / Progress/Circular/BuildingBlocks は
    # Figma 側の名前が Charts/Pie / Progress / Charts/Pie/BuildingBlocks に
    # 変わっていた。書き出しの $meta は「全量 24 set」と言っていた）。
    excluded = set(doc['$meta'].get('excluded') or {})
    # **単体 component も書き出し側に数える**（2026-09-02 に aub から回収）。
    # componentSets だけを見ていたため、Header / Footer / BottomNavigation /
    # EmptyStates が書き出しにあるのに「Figma にしか無い」と報告されていた
    exported = (set(doc['componentSets'])
                | set(doc.get('singleComponents') or {}) | excluded)
    d = compare(saved, now, exported, excluded)
    only_figma, only_export = d['onlyFigma'], d['onlyExport']
    if only_figma or only_export:
        print('**書き出しと Figma でセットの名前が食い違っています。**')
        if only_figma:
            print(f'  Figma にしか無い: {", ".join(only_figma)}')
            print('    → 書き出しを取り直すか、$meta.excluded に理由つきで宣言する')
        if only_export:
            print(f'  書き出しにしか無い: {", ".join(only_export)}')
            print('    → Figma 側で名前が変わった／消えた可能性。**推測で直さず確認する**')
        print()
        # **ここで止めない。** 名前の食い違いを報告した時点で終わっていたため、
        # **値の変化まで一度も比べていませんでした**（2026-08-21 実測）。
        # Waveform が増えた件で止まり、同じ回に変わっていたトグルの
        # エフェクトスタイル（Selected=True が InnerShadow/Neutral/Subtle へ）を
        # 検出できず、ユーザー指摘で気づいた。名前と値は別の話。
        name_drift = True
    else:
        name_drift = False

    # **スタイルの鮮度**（2026-09-02 に aub-familywalk から回収）。
    # component set だけを見ていると、**スタイルの名前や説明が変わっても黙る**。
    # 設定が無ければ「見ていない」と表示する（黙って飛ばさない）。
    style_ng = []
    st = read_styles()
    if st is None:
        print('スタイルの鮮度: **見ていません**'
              '（STYLES_EXPORT / DESCS_EXPORT が設定されていません）')
    else:
        style_ng = compare_styles(st)
        if style_ng:
            print(f'**スタイルが書き出しと食い違っています（{len(style_ng)}件）:**')
            for m in style_ng:
                print(f'  - {m}')
            print()
        else:
            print(f'スタイルの鮮度: 使われている {len(st)} 件の名前と説明が一致')

    if update:
        # **取り直し忘れを拒む。** Figma が動いているのに書き出し本体が
        # 前回の --update から1バイトも変わっていないなら、Plugin API の
        # 取り直しを忘れています（2026-08-21 の監査）。
        moved = bool(d['added'] or d['removed'] or d['changed'])
        same_body = doc['$meta'].get('bodyHash') == body_hash(doc)
        if moved and same_body and '--force' not in sys.argv:
            print(
                '**書き出し本体を取り直していません。**\n'
                f'  Figma は動いています（変わった: {", ".join(d["changed"]) or "なし"}'
                f' / 増えた: {", ".join(d["added"]) or "なし"}'
                f' / 消えた: {", ".join(d["removed"]) or "なし"}）\n'
                '  なのに components.json の componentSets は前回の --update から'
                '変わっていません。\n'
                '  先に design/figma_export_components.js で書き出しを取り直し、'
                'design/figma_pack_components.py --write で差し込んでください。\n'
                '  次の場合だけ --force を付けます:\n'
                '    - 本体を変えなくてよいと分かっている\n'
                '    - **指紋の作り方（node_digest）を変えた**ので全件動いた\n'
                '      （2026-08-22 に id → 名前へ変えたときがこれ）',
                file=sys.stderr)
            return 2
        doc['$meta']['bodyHash'] = body_hash(doc)
        doc['$meta']['bodyHash とは'] = (
            '書き出し本体（componentSets）の sha256 の先頭12桁。'
            '**取り直し忘れを拒むためだけの値。** Figma が動いているのに'
            'ここが前回の --update から変わっていなければ、Plugin API の'
            '取り直しを忘れている（2026-08-21 の監査で追加）')
        doc['$meta']['restDigests'] = dict(sorted(now.items()))
        doc['$meta']['restDigests とは'] = (
            'REST API で読んだセットごとの指紋（design/figma_freshness.py が'
            '計算・更新する）。**Figma が変わったことに気づくためだけの値**で、'
            '内容の正は Plugin API の書き出し本体。'
            '色・余白・並び・文字の寄せを見て、座標は見ない')
        EXPORT.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + '\n',
                          encoding='utf-8')
        print(f'指紋を更新しました（{len(now)} セット）')
        return 0

    if not saved:
        print('指紋がまだ記録されていません。'
              '書き出しを取り直した直後に --update を実行してください')
        return 1

    added, removed, changed = d['added'], d['removed'], d['changed']
    # **見えないものを毎回はっきり言う**（2026-08-22 の監査での是正）。
    # この検査は REST だけで完結させているので、**変数の値**は読めません
    # （`/variables/local` は Enterprise 限定）。今日、ユーザーが3つの変数の
    # 色を変えたのに「Figma は書き出しと同じです」と言ってしまいました。
    print('この検査が見ていないもの: **変数の値**'
          '（REST では読めません）。色やサイズの変数を変えたと言われたら、'
          'design/figma_export_variables.js を回して '
          'design/figma_pack_variables.py で差分を見てください')

    if not (added or removed or changed):
        if name_drift or style_ng:
            what = []
            if name_drift:
                what.append('名前の食い違い')
            if style_ng:
                what.append(f'スタイルのずれ {len(style_ng)}件')
            print(f'値は書き出しと同じです（{len(now)} セット）。'
                  f'**{" と ".join(what)}が残っています**（上の報告を見る）')
            return 1
        print(f'Figma は書き出しと同じです（{len(now)} セット'
              + (f' / スタイル {len(st)} 件' if st else '') + '）')
        return 0

    print('**Figma が書き出しより新しくなっています。**')
    for label, names in (('変わった', changed), ('増えた', added), ('消えた', removed)):
        if names:
            print(f'  {label}: {", ".join(names)}')
    print()
    print('取り直し方: ~/.claude/skills/mobile-harness-setup/references/'
          'figma-fullexport.md の手順で書き出し直し、')
    print('            そのあと python3 design/figma_freshness.py --update')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
