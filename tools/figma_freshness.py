#!/usr/bin/env python3
"""Figma が書き出しより新しくなっていないかを見る（鮮度の検査・テンプレート）。

【テンプレートについて】flash-compose の実運用版のコピー（2026-08-28 回収）。
「案件ごとに埋める」の3定数だけを具体化して <プロジェクト>/design/figma_freshness.py に置く。
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
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ---- 案件ごとに埋める（3つだけ）--------------------------------------------
#: 全量書き出しの components.json。レジストリ参照の案件はレジストリ側を指す
EXPORT = ROOT / '{{書き出しのパス。例: ../design-systems/<名前>/figma/components.json}}'
FILE_KEY = '{{Figma の fileKey}}'
#: 参照しないページ（書き出しと同じ。同名の component set を拾わないため）
SKIP_PAGES = ['{{下書きページ名}}', '{{AI出力ページ名}}']
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


def read_sets() -> dict:
    """参照するページの component set を name → 指紋 で返す。"""
    doc = get(f'https://api.figma.com/v1/files/{FILE_KEY}?depth=1')['document']
    pages = [p for p in doc['children'] if p['name'] not in SKIP_PAGES]
    ids = ','.join(p['id'] for p in pages)
    data = get(f'https://api.figma.com/v1/files/{FILE_KEY}/nodes?ids={ids}')
    found: dict[str, str] = {}
    dup: list[str] = []

    def walk(n, names):
        if n['type'] == 'COMPONENT_SET':
            name = n['name']
            if name in found:
                dup.append(name)
            found[name] = node_digest(n, names)
            return
        for c in (n.get('children') or []):
            walk(c, names)

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


def body_hash(doc: dict) -> str:
    """書き出し本体（componentSets）の指紋。

    **なぜ要るか**（2026-08-21 の監査）: `--update` は `restDigests` を今の
    Figma で上書きするだけで、書き出し本体を読みも比べもしていませんでした。
    そのため **Plugin API の取り直しを忘れて `--update` を先に打つ**と、以後の
    検査は永久に緑になり、表示は「Figma は書き出しと同じです」と断言します。
    本体の指紋を並べて持ち、「Figma は動いたのに本体は動いていない」を拒みます。
    """
    body = json.dumps(doc['componentSets'], ensure_ascii=False, sort_keys=True)
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


def selftest() -> int:
    """網に触らずに [compare] の振る舞いを確かめる。"""
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

    ng = [name for name, ok in cases if not ok]
    print(f'[figma_freshness] selftest {len(cases) - len(ng)}/{len(cases)} 件パス')
    for name in ng:
        print(f'  NG: {name}', file=sys.stderr)
    return 1 if ng else 0


def main() -> int:
    if '--selftest' in sys.argv:
        return selftest()
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
    exported = set(doc['componentSets']) | excluded
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
        if name_drift:
            print(f'値は書き出しと同じです（{len(now)} セット）。'
                  '**名前の食い違いだけが残っています**（上の報告を見る）')
            return 1
        print(f'Figma は書き出しと同じです（{len(now)} セット）')
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
