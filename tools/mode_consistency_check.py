#!/usr/bin/env python3
"""画面の中で、変数のコレクションごとのモードが食い違っている所を報せる（#191・2026-11-04）。

## なぜ要るか

2026-11-04、portfolio のスマホの画面で、Typography のコレクションは SP のモードにしていたのに、Width&Height には
SP を付け忘れていた所が 32 あり、Icon/S の SP の値が使われていなかった。**どの検査にも出なかった。**
値の照合は「Figma に書いてある値」と実装を比べるので、Figma の中でモードを付け忘れると、間違った値どうしが一致する。

## 見るもの

画面の書き出しの `modes=`（節点に明示したモード。2026-11-04 からの器・REST 版が書く）を、親から子へ受け継いで、
**同じ名前のモード（SP など）を持つコレクションどうしが、別のモードになっている**節点を数える。
「同じ名前のモード」は Variables の書き出しの各コレクションの modes から決める（名前を決め打ちしない）。

報せるのは、モードを明示した節点だけ（その下の節点はすべて同じ食い違いを受け継ぐので、数えると同じことを何度も言う）。

## 捕まえないもの

- モードの名前がコレクションごとに違う設計（例: Typography は SP・Width&Height は Mobile）。名前で対応を取るため
- どのモードにすべきか（それはデザイナーが決める）
- 確かめた方法: --self-test（食い違い・受け継ぎ・そろった例・明示の無い書き出し・入力が欠けた場合）

## 終了コード

    0  食い違いは無い
    1  食い違いがある
    2  確かめられなかった（書き出し・Variables が無い、行が1つも無い）
"""

import argparse
import json
import sys
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
sys.path.insert(0, _HERE)
try:
    import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）
finally:
    sys.path.remove(_HERE)


def collection_modes(variables):
    """コレクション名 → そのモードの名前の一覧（先頭が既定）"""
    out = {}
    for name, c in (variables.get("collections") or {}).items():
        if isinstance(c, dict) and isinstance(c.get("modes"), list):
            out[name] = list(c["modes"])
    return out


def frames_of(doc):
    if "frames" in doc:
        return {k: v for k, v in doc["frames"].items() if not k.startswith("$")}
    return {f"{s}/{v}": x for s, cs in (doc.get("componentSets") or {}).items()
            for v, x in (cs.get("variants") or {}).items()}


def own_modes(row):
    for col in row.split("|")[7:]:
        if col.startswith("modes="):
            try:
                return json.loads(col[len("modes="):])
            except json.JSONDecodeError:
                return None
    return {}


def check_frame(name, rows, cols):
    """1 画面ぶん。(場所, コレクション, いまのモード, そろえるモード) の一覧と、明示した節点の数"""
    found, stack, explicit = [], [], 0
    for row in rows:
        parts = row.split("|")
        if len(parts) < 7 or not parts[0].isdigit():
            continue
        depth = int(parts[0])
        while stack and stack[-1][0] >= depth:
            stack.pop()
        eff = dict(stack[-1][1]) if stack else {}
        own = own_modes(row)
        if own is None:
            found.append((f"{name} / {parts[1]}", "modes=", "読めない", "—"))
            continue
        eff.update(own)
        stack.append((depth, eff))
        if not own:
            continue
        explicit += 1
        for mode in sorted(set(eff.values())):
            for col, modes in sorted(cols.items()):
                if mode in modes and eff.get(col, modes[0]) != mode:
                    found.append((f"{name} / {parts[1]}", col, eff.get(col) or f"既定（{modes[0]}）", mode))
    return found, explicit


def main(argv=None):
    ap = argparse.ArgumentParser(description="画面の中で、コレクションごとのモードの食い違いを報せる")
    ap.add_argument("--frames", type=Path, action="append", default=[], help="画面か部品の書き出し（複数可）")
    ap.add_argument("--variables", type=Path, help="Variables の書き出し（export_variables.js）")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if not a.frames or not a.variables:
        print("--frames と --variables が要ります", file=sys.stderr)
        return 2
    try:
        cols = collection_modes(json.loads(a.variables.read_text(encoding="utf-8")))
        docs = [json.loads(p.read_text(encoding="utf-8")) for p in a.frames]
    except (OSError, json.JSONDecodeError) as e:
        print(f"書き出しが読めません: {e}", file=sys.stderr)
        return 2
    if not cols:
        print("Variables の書き出しにコレクションがありません。モードを確かめられません", file=sys.stderr)
        return 2
    found, explicit, n_frames = [], 0, 0
    for d in docs:
        for fid, fr in frames_of(d).items():
            rows = fr.get("rows") if isinstance(fr, dict) else None
            if not isinstance(rows, list):
                continue
            n_frames += 1
            f, e = check_frame(fr.get("name", fid), rows, cols)
            found += f
            explicit += e
    if not n_frames:
        print("画面が1つもありません。**0 件は「食い違いなし」ではなく「見ていない」です**", file=sys.stderr)
        return 2
    if found:
        print(f"**コレクションごとのモードが食い違っています**（{len(found)} 件）:", file=sys.stderr)
        for where, col, now, want in found[:40]:
            print(f"  {where}: {col} が {now}（ほかのコレクションは {want}）", file=sys.stderr)
        print("  Figma でその節点の変数のモードをそろえてください（付け忘れでなければ、どのモードにするかはデザイナーが決める）",
              file=sys.stderr)
        return 1
    if not explicit:
        print(f"モードの食い違い: 画面 {n_frames} 枚に、明示したモードが1つもありません"
              "（2026-11-04 より前の書き出し器で取った書き出しなら、取り直すまで**見ていません**）")
        return 0
    print(f"モードの食い違い: 0 件（画面 {n_frames} 枚・モードを明示した節点 {explicit}）")
    return 0


def self_test():
    import contextlib
    import io
    import tempfile
    ok = True

    def ck(c, m):
        nonlocal ok
        if not c:
            ok = False
            print(f"  NG: {m}")

    cols = {"Typography": ["PC", "SP"], "Width&Height": ["PC", "SP"], "Color": ["Light", "Dark"]}
    m = lambda d: "modes=" + json.dumps(d, ensure_ascii=False, separators=(",", ":"))   # noqa: E731
    f, e = check_frame("S", ["0|S|FRAME|1|1|0|0|" + m({"Typography": "SP"}), "1|A|TEXT|1|1|0|0"], cols)
    ck(f == [("S / S", "Width&Height", "既定（PC）", "SP")] and e == 1, f"**付け忘れを捕まえない**: {f}")
    f, _ = check_frame("S", ["0|S|FRAME|1|1|0|0|" + m({"Typography": "SP", "Width&Height": "SP"}),
                             "1|Card|INSTANCE|1|1|0|0|" + m({"Color": "Dark"})], cols)
    ck(f == [], f"そろっている（受け継いだ SP と別の名前の Dark）のに食い違いと言った: {f}")
    f, _ = check_frame("S", ["0|S|FRAME|1|1|0|0|" + m({"Typography": "SP", "Width&Height": "SP"}),
                             "1|Card|FRAME|1|1|0|0|" + m({"Width&Height": "PC"})], cols)
    ck(len(f) == 2 and {x[1] for x in f} == {"Typography", "Width&Height"},
       f"子で片方だけ戻した食い違いを、受け継いだモードと比べていない: {f}")
    f, _ = check_frame("S", ["0|S|FRAME|1|1|0|0|" + m({"Typography": "SP", "Width&Height": "SP"}),
                             "0|T|FRAME|1|1|0|0|" + m({"Typography": "SP"})], cols)
    ck(len(f) == 1 and f[0][0] == "S / T", f"兄弟（深さが戻った行）に前の行のモードを受け継がせた: {f}")
    with tempfile.TemporaryDirectory() as td:
        fr, vr = Path(td) / "f.json", Path(td) / "v.json"
        vr.write_text(json.dumps({"collections": {k: {"modes": v} for k, v in cols.items()}}), encoding="utf-8")
        fr.write_text(json.dumps({"frames": {"1:1": {"name": "SP_Top", "rows": ["0|SP_Top|FRAME|1|1|0|0|" + m({"Typography": "SP"})]}}}),
                      encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            ck(main(["--frames", str(fr), "--variables", str(vr)]) == 1, "食い違いがあるのに 1 でない")
            fr.write_text(json.dumps({"frames": {"1:1": {"name": "A", "rows": ["0|A|FRAME|1|1|0|0"]}}}), encoding="utf-8")
            ck(main(["--frames", str(fr), "--variables", str(vr)]) == 0, "明示の無い書き出しで 0 でない")
            fr.write_text(json.dumps({"frames": {}}), encoding="utf-8")
            ck(main(["--frames", str(fr), "--variables", str(vr)]) == 2, "画面が無いのに 2 でない")
            ck(main(["--frames", str(fr)]) == 2, "Variables が無いのに 2 でない")
            ck(main(["--frames", str(Path(td) / "none.json"), "--variables", str(vr)]) == 2, "読めないのに 2 でない")
            vr.write_text(json.dumps({"collections": {}}), encoding="utf-8")
            ck(main(["--frames", str(fr), "--variables", str(vr)]) == 2, "コレクションが無いのに 2 でない")
    print("self-test: OK" if ok else "self-test: NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
