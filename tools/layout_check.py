#!/usr/bin/env python3
"""**画面の骨格が、書き出し（frames.json）のとおりに実装されているかを見る。**

## なぜ要るか（2026-09-19・実害）

画面3枚を実装したとき、`design_check.py` は違反0、`swiftc -parse` は全通過、
`verify.sh` は終了コード0でした。**それでも実機では Figma と全く違うものが出ました**
（ユーザー報告:「全然ダメでした」）。

**原因は、書き出しの幾何を写さず、配置を自分で組んだことです。** 例:

    Frame 65 | 420x217 | x=0 y=116 | layout=40,28,40,28,12,VERTICAL,HUG,FIXED

上から 116 の位置に置く設計なのに、実装は `ZStack` の中央に置いていました。

**この食い違いを見る段が、ハーネスに1つもありませんでした**（design-harness #133）。
「書き出しの検算」は書き出しの中の矛盾、「実装網羅」は部品名の突き合わせで、
**どちらも実装の配置を見ません。** トークンと部品名だけ合っていれば緑になります。

## この道具が見るもの

`design/screen-map.json` に、**書き出しの行と実装の View の対応**を宣言します。
この道具は行ごとに:

1. **書き出しの行が変わっていないか**（変わったら宣言が古い。落とす）
2. **宣言した値が実装にあるか**——余白・すき間・向き・位置を、
   **`Theme/Metrics.swift` の段を解いて数で**突き合わせます
   （`Space.xxxl` → 40 と解いて、書き出しの 40 と比べます）

## この道具が見ないもの（正直に）

**出た絵の実際の寸法は見ません。** SwiftUI がレイアウトを確定させるまで寸法は
存在せず、それには Xcode が要ります（司令塔の MacBook Air には入っていません）。

**ここで見るのは「書いた値が書き出しと合っているか」までです。**
「出た絵が合っているか」は、Mac mini で走らせる実測のテストが要ります（別の段）。

- 確かめた方法: --self-test（宣言した値を1つ崩すと落ちること）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: 段の名前 → 値（`Theme/Metrics.swift` から読む）
TOKEN_RX = re.compile(r"static let (\w+): CGFloat = ([0-9.]+)")
#: `// layout-anchor: <鍵>` から次の anchor（か末尾）までを、その行の実装とみなす
ANCHOR_RX = re.compile(r"//\s*layout-anchor:\s*(\S+)")


def token_table(path: Path) -> dict[str, float]:
    """`Space.xs` のような段を数に解く表を作る。"""
    out: dict[str, float] = {}
    if not path.is_file():
        return out
    ns = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"enum (\w+) \{", line.strip())
        if m:
            ns = m.group(1)
        m = TOKEN_RX.search(line)
        if m and ns:
            out[f"{ns}.{m.group(1)}"] = float(m.group(2))
    return out


def parse_row(row: str) -> dict:
    """`深さ|名前|型|w|h|x|y|k=v|…` を読む。"""
    p = row.split("|")
    out = {"depth": int(p[0]), "name": p[1], "type": p[2]}
    for k, i in (("w", 3), ("h", 4), ("x", 5), ("y", 6)):
        if len(p) > i and p[i] not in ("", "-"):
            try:
                out[k] = float(p[i])
            except ValueError:
                pass
    for seg in p[7:]:
        if "=" in seg:
            k, v = seg.split("=", 1)
            out[k] = v
    if "layout" in out:
        f = out["layout"].split(",")
        if len(f) >= 10:
            out["pad"] = [float(x) for x in f[:4]]     # 上 右 下 左
            out["gap"] = float(f[4])
            out["dir"] = f[5]
            out["sizeW"], out["sizeH"] = f[6], f[7]
    return out


#: 行のコメント。**数を数える前に落とします。**
COMMENT_RX = re.compile(r"//[^\n]*")


def numbers_in(text: str, tokens: dict[str, float]) -> list[float]:
    """実装の断片にある数を、段を解いたうえで集める。

    **コメントは落とします。** 書き出しの値を説明として書くことがあり
    （「上から 116」など）、それを実装の値として数えると**崩しても通ります**
    （2026-09-19 に実際に空振りしました。`.padding(.top, 7)` に崩しても、
     コメントの 116 を拾って合格していた）。
    """
    text = COMMENT_RX.sub("", text)
    out: list[float] = []
    for name, val in tokens.items():
        if re.search(r"\b" + re.escape(name) + r"\b", text):
            out.append(val)
    for m in re.finditer(r"(?<![\w.])(\d+(?:\.\d+)?)(?![\w.])", text):
        out.append(float(m.group(1)))
    return out


#: 印の塊の終わり。**次の `private var` / `private func` / `var body` まで**を
#: その印の実装とみなす。**次の印までではありません**——入れ子の View に内側の印を
#: 置くと、外側の塊が印の位置で切れてしまい、外側の値が見えなくなるためです
#: （2026-09-19 に実際に踏みました）。
MEMBER_RX = re.compile(r"^\s*(?:private |internal |public )?(?:var|func|enum|struct) ", re.M)


def anchored(src: str, key: str) -> str | None:
    """`// layout-anchor: <鍵>` から、その View の終わりまでを返す。

    **内側に別の印があっても切りません。** 外側の塊には外側の値が要るためです。
    """
    hits = [(m.start(), m.group(1)) for m in ANCHOR_RX.finditer(src)]
    for pos, k in hits:
        if k != key:
            continue
        # 印の下の最初の宣言（var/func）を飛ばし、その次の宣言までを塊とする
        first = MEMBER_RX.search(src, pos)
        if not first:
            return src[pos:]
        nxt = MEMBER_RX.search(src, first.end())
        return src[pos:nxt.start() if nxt else len(src)]
    return None


def check(conf_path: Path, root: Path) -> int:
    if not conf_path.is_file():
        print(f"宣言がありません: {conf_path}\n"
              f"  **確かめられないので落とします。**0 件ではありません", file=sys.stderr)
        return 2
    conf = json.loads(conf_path.read_text(encoding="utf-8", errors="replace"))
    frames_path = (root / conf["frames"]).resolve()
    if not frames_path.is_file():
        print(f"画面の書き出しがありません: {frames_path}", file=sys.stderr)
        return 2
    frames = json.loads(frames_path.read_text(encoding="utf-8", errors="replace"))["frames"]
    # **案件の置き場を既定にしません**（design-harness #133・2026-09-24）。
    # 共有層へ上げるときに `Sources/PlantTalk/Theme/Metrics.swift` が既定のまま
    # 残っていると、**他の案件では黙って 0 件の表で走ります。**
    if not conf.get("tokens"):
        print("宣言に `tokens` がありません（段の表の置き場）。\n"
              '  例: {"tokens": "Sources/<名前>/Theme/Metrics.swift"}\n'
              "  **既定値を持ちません。**案件ごとに違うので、推測しません。",
              file=sys.stderr)
        return 2
    tokens = token_table(root / conf["tokens"])
    if not tokens:
        print(f"段の表が読めません（{conf['tokens']}）。"
              "**数を解けないので落とします**", file=sys.stderr)
        return 2

    errs: list[str] = []
    checked = 0
    skipped = 0
    for key, e in conf["rows"].items():
        frame_id, idx = key.rsplit("#", 1)
        rows = frames.get(frame_id, {}).get("rows")
        if not rows or int(idx) >= len(rows):
            errs.append(f"  {key}: 書き出しにその行がありません（宣言が古い）")
            continue
        row = rows[int(idx)]
        if row[:60] != e["行"][:60]:
            errs.append(f"  {key}: **書き出しの行が変わっています**（宣言が古い）\n"
                        f"    宣言: {e['行'][:80]}\n"
                        f"    いま: {row[:80]}")
            continue
        if e.get("写さない"):
            skipped += 1
            if not e.get("理由"):
                errs.append(f"  {key}: 写さないなら**理由が要ります**")
            continue
        src_path = root / e["実装"]
        if not src_path.is_file():
            errs.append(f"  {key}: 実装のファイルがありません: {e['実装']}")
            continue
        blk = anchored(src_path.read_text(encoding="utf-8", errors="replace"), key)
        if blk is None:
            errs.append(f"  {key}: 実装に印がありません。"
                        f"`// layout-anchor: {key}` を、当たる View の直前に置いてください")
            continue
        got = numbers_in(blk, tokens)
        parsed = parse_row(row)
        for want, label in e["要る値"].items():
            v = None
            if want == "gap":
                v = parsed.get("gap")
            elif want in ("padT", "padR", "padB", "padL"):
                i = ["padT", "padR", "padB", "padL"].index(want)
                v = parsed.get("pad", [None] * 4)[i]
            elif want in ("w", "h", "x", "y"):
                v = parsed.get(want)
            if v is None:
                errs.append(f"  {key}: 書き出しに {want} がありません（宣言が誤り）")
                continue
            if not any(abs(g - v) < 0.51 for g in got):
                errs.append(f"  {key}: **{label}が合いません**。"
                            f"書き出しは {want}={v:g} ですが、実装のこの塊に出てきません\n"
                            f"    見た数: {sorted(set(got))[:12]}")
            checked += 1
    if errs:
        print("画面の骨格が書き出しと合っていません:")
        print("\n".join(errs))
        print(f"\n  見た行 {len(conf['rows'])} 件 / 値 {checked} 件 / 写さないと宣言 {skipped} 件")
        return 1
    print(f"画面の骨格: 行 {len(conf['rows'])} 件・値 {checked} 件が書き出しと合っています"
          f"（写さないと宣言 {skipped} 件）")
    print("  **出た絵の実際の寸法は見ていません。**それには Xcode が要ります（別の段）")
    return 0


def self_test() -> int:
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        (r / "Sources/PlantTalk/Theme").mkdir(parents=True)
        (r / "Sources/PlantTalk/Theme/Metrics.swift").write_text(
            "enum Space {\n    static let xxxl: CGFloat = 40\n}\n", encoding="utf-8")
        (r / "ui.swift").write_text(
            "// layout-anchor: F#0\nVStack { }.padding(.top, Space.xxxl)\n", encoding="utf-8")
        (r / "frames.json").write_text(json.dumps(
            {"frames": {"F": {"rows": ["1|A|FRAME|420|217|0|116|layout=40,0,0,0,12,VERTICAL,HUG,FIXED,MIN,CENTER"]}}}),
            encoding="utf-8")
        conf = {"frames": "frames.json",
                "tokens": "Sources/PlantTalk/Theme/Metrics.swift", "rows": {
            "F#0": {"行": "1|A|FRAME|420|217|0|116|layout=40,0,0,0,12,VERTICAL,HUG,FIXED,MIN,CENTER",
                    "実装": "ui.swift", "要る値": {"padT": "上の余白"}}}}
        cp = r / "c.json"
        cp.write_text(json.dumps(conf), encoding="utf-8")
        if check(cp, r) != 0:
            print("self-test: **合っているのに落ちました**", file=sys.stderr)
            return 1
        # 値を1つ崩すと落ちること
        (r / "ui.swift").write_text(
            "// layout-anchor: F#0\nVStack { }.padding(.top, 7)\n", encoding="utf-8")
        if check(cp, r) == 0:
            print("self-test: **崩したのに通りました**", file=sys.stderr)
            return 1
        # **コメントに書いた数では通らないこと**（2026-09-19 の空振り）
        (r / "ui.swift").write_text(
            "// layout-anchor: F#0\n// 上の余白は 40\nVStack { }.padding(.top, 7)\n",
            encoding="utf-8")
        if check(cp, r) == 0:
            print("self-test: **コメントの数で通りました**", file=sys.stderr)
            return 1
        (r / "ui.swift").write_text(
            "// layout-anchor: F#0\nVStack { }.padding(.top, Space.xxxl)\n", encoding="utf-8")
        # 書き出しが変わったら落ちること
        (r / "ui.swift").write_text(
            "// layout-anchor: F#0\nVStack { }.padding(.top, Space.xxxl)\n", encoding="utf-8")
        (r / "frames.json").write_text(json.dumps(
            {"frames": {"F": {"rows": ["1|A|FRAME|420|217|0|999|layout=99,0,0,0,12,VERTICAL,HUG,FIXED,MIN,CENTER"]}}}),
            encoding="utf-8")
        if check(cp, r) == 0:
            print("self-test: **書き出しが変わったのに通りました**", file=sys.stderr)
            return 1
    # **`tokens` の宣言が無ければ 2**（#133）。共有層へ上げるとき、案件の置き場が
    # 既定のまま残っていると**他の案件では黙って 0 件の表で走る**
    with tempfile.TemporaryDirectory() as td2:
        r2 = Path(td2)
        # **通る形から `tokens` だけを抜く。**他の理由で 2 になっては試験にならない
        (r2 / "Sources/PlantTalk/Theme").mkdir(parents=True)
        (r2 / "Sources/PlantTalk/Theme/Metrics.swift").write_text(
            "enum Space { static let xxxl: CGFloat = 40 }\n", encoding="utf-8")
        (r2 / "ui.swift").write_text(
            "// layout-anchor: F#0\nVStack { }.padding(.top, Space.xxxl)\n", encoding="utf-8")
        (r2 / "frames.json").write_text(json.dumps(
            {"frames": {"F": {"rows": ["1|A|FRAME|420|217|0|116|"
                                       "layout=40,0,0,0,12,VERTICAL,HUG,FIXED,MIN,CENTER"]}}}),
            encoding="utf-8")
        cp2 = r2 / "c.json"
        cp2.write_text(json.dumps({"frames": "frames.json", "rows": {
            "F#0": {"行": "1|A|FRAME|420|217|0|116|"
                          "layout=40,0,0,0,12,VERTICAL,HUG,FIXED,MIN,CENTER",
                    "実装": "ui.swift", "要る値": {"padT": "上の余白"}}}}), encoding="utf-8")
        if check(cp2, r2) != 2:
            print("self-test: **tokens の宣言が無いのに通りました**", file=sys.stderr)
            return 1

    print("self-test: 通った（合えば 0 / 値を崩せば落ちる / コメントの数では通らない / 書き出しが変われば落ちる）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="画面の骨格が書き出しどおりか")
    ap.add_argument("--config", default="design/screen-map.json")
    # **案件の根は「いま居る場所」を既定にします**（#133・共有層へ上げたため）。
    # 道具の位置から求めると、`design/harness/tools/` に置いた瞬間に
    # **ハーネスの中を案件だと思い込みます**（2026-09-24 に踏みました）。
    ap.add_argument("--root", default=".")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    return check(Path(a.root) / a.config, Path(a.root))


if __name__ == "__main__":
    sys.exit(main())
