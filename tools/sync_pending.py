"""design/values/_pending.json を、いまの検査の状況に合わせて作り直す（テンプレート）。

【テンプレートについて】aub-familywalk の実運用版のコピー（2026-08-28 回収）。
declaredAt を日付に置き換えて <プロジェクト>/design/sync_pending.py に置く。
検査ファイルの探索範囲（test/ 配下の *.dart）はスタックに合わせて変える。

【_pending.json の位置づけ】着工の道具であってリリースの免罪符ではない。
「これから検査を書く」を宣言させ、黙って素通りする状態を作らないためのリスト。
**本番リリース時は 0 件（production-gate.md の条件3）。** 宣言が残ったまま
リリースに進まない。

ゲート（test/design/values_gate_test.dart）は「measured のキーに検査があるか、
無いなら _pending.json に宣言してあるか」をキー単位で見る。検査を書いたら
この治具を回して宣言を減らす。**手で数字をいじらない。**
"""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
VALUES = ROOT / 'design' / 'values'


def main() -> int:
    measured = []
    for f in sorted(VALUES.glob('*.json')):
        if f.name.startswith('_'):
            continue
        doc = json.loads(f.read_text())
        for key, items in doc.items():
            if key == '$meta':
                continue
            measured += [e['key'] for e in items if e.get('status') == 'measured']

    source = ''
    for f in sorted((ROOT / 'test').rglob('*.dart')):
        if f.name == 'values_gate_test.dart':
            continue
        source += f.read_text()

    uncovered = sorted(k for k in measured if k not in source)
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
        'ルール': '検査を書いたら python3 design/sync_pending.py を回す。'
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
