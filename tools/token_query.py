#!/usr/bin/env python3
"""生の値からトークン名を逆引きする。

Figma の実測値や既存コードのリテラルが、どのトークンに当たるのかを調べる道具。
**近い値しか無い場合は「スケール外」として近傍を出す**ので、
「トークンに無い値を使おうとしている」ことにその場で気づける。

    python3 <名前>/token_query.py "#ff5800"     色から引く
    python3 <名前>/token_query.py 16            数値から引く
    python3 <名前>/token_query.py Body/Regular/M  名前から引く（中身を解決して出す）
    python3 <名前>/token_query.py 13 --near 3   近傍を広めに出す

このスクリプトはトークンの構造を決め打ちしません（tokens.json を再帰的に走査して
すべての葉を索引にします）。どのデザインシステムでもそのまま動きます。

完全一致が1件も無ければ終了コード 1 を返す（スケール外の値だったということ）。
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

HERE = Path(__file__).parent
TOKENS = HERE / "tokens" / "tokens.json"

DEFAULT_NEAR = 2      # 近傍として出す件数
COLOR_RE = re.compile(r"^#?[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?$")


def walk(node, path=()):
    """トークンの木を再帰的に歩き、(パス, 値) を全部出す。

    - dict の "value" と "alias" は Figma のセマンティック変数の形。
      value を値、alias を別名として扱う
    - list は TextStyles の形（name を持つ dict の並び）
    - "$meta" は同期メモなので飛ばす
    """
    if isinstance(node, dict):
        if "value" in node and not isinstance(node["value"], (dict, list)):
            yield "/".join(path), node["value"], node.get("alias")
            return
        for k, v in node.items():
            if k.startswith("$") or k.startswith("_"):
                continue
            yield from walk(v, path + (k,))
    elif isinstance(node, list):
        for item in node:
            if isinstance(item, dict) and "name" in item:
                yield from walk({k: v for k, v in item.items() if k != "name"},
                                path + (item["name"],))
    else:
        yield "/".join(path), node, None


def norm_color(s):
    """色を #rrggbbaa に正規化する。比較のため小文字にそろえる。"""
    s = s.lstrip("#").lower()
    if len(s) == 6:
        s += "ff"
    return "#" + s


def as_number(v):
    """数値として比較できるなら float を返す。できなければ None。"""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    near_n = DEFAULT_NEAR
    for a in sys.argv[1:]:
        if a.startswith("--near"):
            m = re.search(r"\d+", a)
            if m:
                near_n = int(m.group())

    if not args:
        print(__doc__)
        return 1
    query = args[0]

    if not TOKENS.exists():
        print(f"トークンが見つかりません: {TOKENS}")
        return 1

    index = list(walk(json.loads(TOKENS.read_text(encoding="utf-8"))))

    exact, near = [], []

    if COLOR_RE.match(query):
        # ── 色で引く ────────────────────────────────────────────────
        want = norm_color(query)
        wr, wg, wb, wa = (int(want[i:i + 2], 16) for i in (1, 3, 5, 7))
        for path, val, alias in index:
            if not (isinstance(val, str) and COLOR_RE.match(val)):
                continue
            got = norm_color(val)
            if got == want:
                exact.append((path, val, alias, None))
            else:
                r, g, b, a = (int(got[i:i + 2], 16) for i in (1, 3, 5, 7))
                # 単純な RGB 距離。知覚的な差ではないが、写し間違いの発見には十分
                d = ((r - wr) ** 2 + (g - wg) ** 2 + (b - wb) ** 2) ** 0.5
                d += abs(a - wa)      # 不透明度違いも差として数える
                near.append((d, path, val, alias))
        kind = "色"

    elif as_number(query.replace(".", "", 1)) is not None or query.isdigit():
        # ── 数値で引く ──────────────────────────────────────────────
        want = float(query)
        for path, val, alias in index:
            n = as_number(val)
            if n is None:
                continue
            if n == want:
                exact.append((path, val, alias, None))
            else:
                near.append((abs(n - want), path, val, alias))
        kind = "数値"

    else:
        # ── 名前で引く（部分一致）────────────────────────────────────
        q = query.lower()
        # テキストスタイルの中身は Size/XXS のような別トークンの名前で書かれている。
        # そのまま出しても実際の値が分からないので、引けるものは解決して併記する
        by_path = {p: v for p, v, _ in index}
        for path, val, alias in index:
            if q not in path.lower():
                continue
            resolved = None
            if isinstance(val, str) and not COLOR_RE.match(val):
                hits = [v for p, v in by_path.items()
                        if p == val or p.endswith("/" + val)]
                if len(set(map(str, hits))) == 1:
                    resolved = hits[0]
            exact.append((path, val, alias, resolved))
        kind = "名前"
        near = []

    print(f"\n■ {kind}で逆引き: {query}\n")

    if exact:
        print(f"  一致 — {len(exact)} 件")
        for path, val, alias, resolved in exact:
            tail = f"  ← {alias}" if alias else ""
            if resolved is not None:
                tail += f"  = {resolved}"
            print(f"    {path:<40} {val}{tail}")
    else:
        print("  一致するトークンはありません。")

    if near and not exact:
        print(f"\n  近い値 — 上位 {near_n} 件（**スケールには無い値です**）")
        for d, path, val, alias in sorted(near)[:near_n]:
            tail = f"  ← {alias}" if alias else ""
            print(f"    {path:<40} {val}{tail}")
        print("\n  この値はトークンに無いので、そのまま実装しないでください。"
              "\n  近い値に寄せるか、Figma の Variables への追加を検討します。")

    print()
    return 0 if exact else 1


if __name__ == "__main__":
    sys.exit(main())
