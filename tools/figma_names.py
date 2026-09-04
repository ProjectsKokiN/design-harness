"""Figma の名前 → Dart の識別子。**規則はここ1つだけ。**

**この実装が正本です**（2026-09-02 に aub-familywalk から共有層へ回収）。
生成器も検査も、ここを import します。案件側に複製しないでください。

回収の理由: `impl_coverage_check.identifier_of` が別実装を持っており、
文書の「唯一の正」と食い違っていました（`Icon/XXL` → 実装 `iconXXL`・
文書 `iconXxl`）。planttalk の実測では、この差が誤検出164件のうち21件の
原因になっていました。**aub の実装だけが文書の3例すべてに一致します。**

なお planttalk が提案した1行の修正（区切りの中も全部小文字にする）は
**誤りです**。実測すると `ChipsGroups` → `chipsgroups`・
`BottomNavigationBuildingBlocksIcon` → 全部小文字になり、414 と aub の
部品の識別子が9〜10件壊れます。**頭字語だけを Title 化する**のが正しい規則で、
それを実装しているのが下の `_CAMEL` です。

    Figma 名を `/` と `&` で区切り、記号を落として lowerCamelCase で連結

    Solid/Primary/40                     → solidPrimary40
    Frame/Action/Neutral/Default/Enabled → frameActionNeutralDefaultEnabled
    Icon/XXL                             → iconXxl
    Width&Heights                        → widthHeights
    ChipsGroups                          → chipsGroups
    DropShadow/Neutral/Default           → dropShadowNeutralDefault

**言い換えを作らない。** 短い別名を付けると、カタログで Figma と突き合わせる
たびに読み替えが要る。flash-compose では 17 件・235 箇所を機械置換して
規則へ寄せ直した（2026-08-21）。
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

#: Figma 名を分割する記号。
_SPLIT = re.compile(r'[/&\s]+')
#: 識別子に残さない記号。
_DROP = re.compile(r'[^0-9A-Za-z]')


def to_identifier(name: str) -> str:
    """Figma 名を lowerCamelCase の識別子にする。"""
    parts = [_DROP.sub('', p) for p in _SPLIT.split(name)]
    parts = [p for p in parts if p]
    if not parts:
        raise ValueError(f'識別子にできない名前です: {name!r}')
    out = [_word(parts[0], first=True)]
    out += [_word(p) for p in parts[1:]]
    ident = ''.join(out)
    if ident[0].isdigit():
        raise ValueError(f'識別子が数字で始まります: {name!r} → {ident}')
    return ident


#: 区切りの中の大文字の切れ目。`DropShadow` → `Drop` + `Shadow`、`XXL` → `XXL`。
_CAMEL = re.compile(r'[0-9]+|[A-Z]+(?![a-z])|[A-Z][a-z]*|[a-z]+')


def _word(p: str, first: bool = False) -> str:
    """1語ぶん。

    **頭字語は連ねない**（`XXL` → `Xxl`）。大文字を連ねると `iconXXL` と
    `iconXxl` の2通りが生まれ、規則が2つになってしまう。

    **区切りの中の大文字の切れ目は残す**（`DropShadow` → `dropShadow`）。
    ここを潰すと `dropshadowNeutralDefault` になり、Figma の名前と
    突き合わせるときに読み替えが要る（2026-08-29 に `ChipsGroups` が
    `chipsgroups` になって気づいた）。
    """
    if p.isdigit():
        return p
    subs = _CAMEL.findall(p) or [p]
    out = []
    for i, s in enumerate(subs):
        w = s if s.isdigit() else (s[0].upper() + s[1:].lower())
        out.append(w[0].lower() + w[1:] if (first and i == 0) else w)
    return ''.join(out)


def self_test() -> int:
    """規則の実例。変えたらここも直す。"""
    cases = {
        'Solid/Primary/40': 'solidPrimary40',
        'Frame/Action/Neutral/Default/Enabled': 'frameActionNeutralDefaultEnabled',
        'Icon/XXL': 'iconXxl',
        'Width&Heights': 'widthHeights',
        'ChipsGroups': 'chipsGroups',
        'DropShadow/Neutral/Default': 'dropShadowNeutralDefault',
        'BottomNavigationBuildingBlocksIcon': 'bottomNavigationBuildingBlocksIcon',
        'Label/JP/Bold/M': 'labelJpBoldM',
        'None': 'none',
        'Infinity': 'infinity',
    }
    bad = {k: (v, to_identifier(k)) for k, v in cases.items()
           if to_identifier(k) != v}
    for k, (want, got) in bad.items():
        print(f'self-test NG: {k!r} → {got}（期待 {want}）')
    # 識別子にできない名前で落ちること（規律: 落ちるケースを持つ）
    for bad_name in ('', '///', '40'):
        try:
            to_identifier(bad_name)
        except ValueError:
            pass
        else:
            print(f'self-test NG: {bad_name!r} を通した'); bad[bad_name] = ('例外', '通過')
    print('self-test:', 'OK' if not bad else 'NG')
    return 1 if bad else 0


if __name__ == '__main__':
    import sys
    sys.exit(self_test())
