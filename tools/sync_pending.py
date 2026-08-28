"""design/values/_pending.json を、いまの検査の状況に合わせて作り直す（テンプレート）。

【テンプレートについて】aub-familywalk の実運用版のコピー（2026-08-28 回収）。
**コピーせず submodule のものを直接呼ぶ**（2026-08-28 にコピー配布をやめた）。
    python3 design/harness/tools/sync_pending.py
検査ファイルの探索範囲（test/ 配下の *.dart）はスタックに合わせて変える。

【_pending.json の位置づけ】着工の道具であってリリースの免罪符ではない。
「これから検査を書く」を宣言させ、黙って素通りする状態を作らないためのリスト。
**本番リリース時は 0 件（production-gate.md の条件3）。** 宣言が残ったまま
リリースに進まない。

ゲート（test/design/values_gate_test.dart）は「measured のキーに検査があるか、
無いなら _pending.json に宣言してあるか」をキー単位で見る。検査を書いたら
この治具を回して宣言を減らす。**手で数字をいじらない。**
"""

import argparse
import json
import pathlib
import sys

# submodule から直接呼べる（コピー不要。aub 第2便の要望3: tools がコピー配布だと
# エンジンを一本化した理由と同じ乖離が tools で再発する）。
#   python3 design/harness/tools/sync_pending.py            … cwd の design/values を見る
#   python3 <どこか>/sync_pending.py --values <パス>        … 明示指定
_ap = argparse.ArgumentParser(description="_pending.json を検査の現状から作り直す")
_ap.add_argument("--values", type=pathlib.Path, default=None,
                 help="design/values の場所（既定: cwd/design/values、"
                      "無ければこのファイルの位置から推定）")
_args = _ap.parse_args()
if _args.values:
    VALUES = _args.values.resolve()
elif (pathlib.Path.cwd() / 'design' / 'values').is_dir():
    VALUES = pathlib.Path.cwd() / 'design' / 'values'
else:
    VALUES = pathlib.Path(__file__).resolve().parent.parent / 'design' / 'values'
ROOT = VALUES.parent.parent


def main() -> int:
    # 「status を持つのは entries だけ」と決めて、そこだけを見る
    # （flash-compose 2026-08-28: values のトップキーは案件で違い、
    # 文字列の配列を持つキー（notSurveyed 等）で AttributeError になった。
    # 前提が崩れたときは読める失敗をする）。
    measured = []
    no_assert = []
    for f in sorted(VALUES.glob('*.json')):
        if f.name.startswith('_'):
            continue
        doc = json.loads(f.read_text())
        entries = doc.get('entries')
        if entries is None:
            continue                      # entries を持たないファイルは対象外
        if not isinstance(entries, list) or any(
                not isinstance(e, dict) for e in entries):
            print(f'この案件の values は形が違います: {f.name} の entries が'
                  f'記録の配列ではありません。', file=sys.stderr)
            return 2
        for e in entries:
            if e.get('status') != 'measured':
                continue
            key = e.get('key')
            if not key:
                continue
            measured.append(key)
            # 「検査があるか」は記録側の assert フラグで判定する
            # （flash-compose 2026-08-28: 文字列一致は、対応表から動的に組む
            # テストを数え落とし、コメントで触れただけのものを数え過ぎる。
            # 「名前が出るか」と「値を照合しているか」は別）。
            # assert: true の嘘は values ゲートが見張る（照合が無ければ落ちる）。
            if not e.get('assert'):
                no_assert.append(key)

    uncovered = sorted(no_assert)
    covered = len(measured) - len(uncovered)

    out = VALUES / '_pending.json'
    doc = json.loads(out.read_text()) if out.exists() else {'$meta': {}}
    prev_ceiling = doc.get('$meta', {}).get('ceiling')

    # ラチェット（aub-familywalk 提案・2026-08-28）:
    # 宣言した瞬間に緑になる仕組みは、減らさなくても誰も困らない
    # （aub で 169 件たまっていた）。「増えたら赤・減れば基準も下がる」に変える。
    # リリース条件（production-gate 条件3）は 0 のまま。これは日々の歯止め。
    ceiling = prev_ceiling if isinstance(prev_ceiling, int) else len(uncovered)
    exceeded = len(uncovered) > ceiling
    if not exceeded:
        ceiling = len(uncovered)      # 減ったら基準も下げる（戻せない）

    from datetime import date
    doc['$meta'] = {
        'unit': 'まだ検査が書かれていない measured のキー。',
        'なぜ必要か': 'ゲートをキー単位にすると、記録を足した瞬間に落ちる。'
                      '「これから検査を書く」ことを明示的に宣言させ、'
                      '黙って素通りする状態を作らないためのリスト。',
        'ルール': '検査を書いたら python3 design/harness/tools/sync_pending.py を回す。'
                  '空になったら、このファイルごと消してよい。'
                  'ceiling は自動で下がる。手で上げない。',
        'declaredAt': date.today().isoformat(),
        'count': len(uncovered),
        'ceiling': ceiling,
    }
    doc['keys'] = uncovered
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + '\n')
    print(f'記録 {len(measured)} 件 / 検査あり {covered} 件 / 宣言 {len(uncovered)} 件'
          f'（上限 {ceiling}）')
    if exceeded:
        print(f'NG: 宣言が上限 {ceiling} を超えました（{len(uncovered)} 件）。'
              f'検査を書かずに記録だけ増やしています。', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
