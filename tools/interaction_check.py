#!/usr/bin/env python3
"""押した状態を試験が一度も描かないのを止める（2026-09-04 新設・#27 / #28）。

## 実害（aub-familywalk）

**試験 816 件が緑のまま、実機のリリース版が落ちていました。**
開いているタブのボトムナビを押すと、画面が灰色の箱になって帯ごと消えます。
3つのトップ画面すべて。

原因は2つ重なっています。

### 1. `tester.tap` は押した見た目を一度も描かない（#27）

`tap` は **pointer down → up を、間にフレームを挟まずに**送ります。
`onTapDown` の `setState` で押した状態になっても、**次のフレームが来る前に
`onTapUp` で戻る**ので、`build` が押した状態で呼ばれることが一度もありません。

**実機は違います。** 人の指は数百ミリ秒置かれるので、その間に何フレームも
描かれます。実測:

| 試験の書き方 | 結果 |
|---|---|
| `await tester.tap(…)` | **通る**（実機は落ちる） |
| `startGesture` + `pump(60ms)` | **落ちる**（実機と同じ） |

### 2. Figma に無い組み合わせへ実装が動きうる（#28）

`BottomNavigationBuildingBlocksIcon` は `Selected=True` の側が `Enabled` の
1つだけで、`True|Pressed` がありません。デザイナーの判断としては自然です
（選ばれたタブに押した見た目は要らない）。**実装はそれを知らずに引きに行き、
落ちました。**

生成された面の表は**引けない鍵で落ちる**ようになっています（正しい設計）。
問題は、**実装がその鍵に到達しうることを、誰も事前に見ていない**ことです。

## 見るもの

    python3 tools/interaction_check.py --config design/interaction.json

| 面 | 見るもの |
|---|---|
| `--tests` | 状態の軸を持つ部品の試験が、**`startGesture` を1回以上含むか** |
| `--variants` | 書き出しの**穴のある component set** を一覧にする |

## 捕まえないもの

- 押したときの**見た目が正しいか**（画像で合否は判断しない方針のまま）
- 実装がその穴へ**実際に動くか**。一覧を出すところまでで、判断は人がします
- 確かめた方法: --self-test
"""

import argparse
import json
import re
import sys
from itertools import product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

#: 状態の軸らしい名前（押した・触れた見た目を持つ）
STATE_AXES = ("State", "state", "状態")
#: 押し方
TAP_RX = re.compile(r"\btester?\.\w*tap\w*\(|\bt\.tap\(")
HOLD_RX = re.compile(r"\bstartGesture\(|\baddPointer\(|\bhover\(")


def variant_rows(v):
    """その component set の変異の鍵を返す。**書き出しの形は1つではない。**

    414 の実データ: `axisOrder`（軸の名前）＋ `colors[].k`（`False|Enabled`）。
    `k` が `-` の行は「全変異に共通」の意味なので数えない。
    ひな形の `componentVariantList` の形も受ける。
    """
    vl = v.get("componentVariantList") or v.get("variantList")
    if isinstance(vl, dict) and vl.get("axes"):
        return vl["axes"], [r for r in (vl.get("values") or []) if r != "-"]
    if isinstance(vl, list) and len(vl) == 2 and isinstance(vl[0], list):
        return vl[0], [r for r in vl[1] if r != "-"]
    axes = v.get("axisOrder")
    if not axes:
        return None, None
    rows = set()
    for key in ("colors", "layout", "texts", "effects"):
        for r in (v.get(key) or []):
            if isinstance(r, dict) and isinstance(r.get("k"), str) and r["k"] != "-":
                rows.add(r["k"])
    return axes, sorted(rows)


def variant_holes(doc):
    """軸の総当たりに対して、書き出しに無い組み合わせを返す。"""
    sets = doc.get("componentSets") or doc
    out = {}
    for name, v in sorted(sets.items() if isinstance(sets, dict) else []):
        if not isinstance(v, dict):
            continue
        axes, rows = variant_rows(v)
        if not axes or not rows:
            continue
        parts = [r.split("|") for r in rows]
        if any(len(p) != len(axes) for p in parts):
            continue          # 軸の数と鍵の形が合わない。数えない
        vals = [sorted({p[i] for p in parts}) for i in range(len(axes))]
        have = set(rows)
        miss = ["|".join(c) for c in product(*vals) if "|".join(c) not in have]
        if miss:
            out[name] = {"axes": axes, "あるもの": len(have),
                         "総当たり": len(have) + len(miss), "欠け": miss}
    return out


def tests_without_hold(test_dir, targets):
    """状態の軸を持つ部品の試験が、押しっぱなしを1回も使っていないか。"""
    if not test_dir or not test_dir.exists():
        return None
    out = []
    for f in sorted(test_dir.rglob("*")):
        if not f.is_file() or f.suffix != ".dart":
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        # **コメントの中の名前は「触っている」に数えない。** aub の実測（2026-09-05）:
        # catalog_test.dart は `Images` をコメントで1回書いているだけなのに
        # 「Images を tap だけで触っている」と出た。分母に入れるのはコードの行だけ
        code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("//"))
        hits = [t for t in targets if t in code]
        if not hits:
            continue
        if TAP_RX.search(text) and not HOLD_RX.search(text):
            out.append((f, sorted(hits)[:3]))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="押した状態を試験が描いているか")
    ap.add_argument("--config", type=Path, default=Path("design/interaction.json"))
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    if not args.config.exists():
        print(f"設定がありません: {args.config}\n"
              f'  例: {{"export": "design/figma/components.json",\n'
              f'        "tests": "test", "declaredHoles": {{}}}}\n'
              f"  **押した状態を試験が描いているかを、誰も見ていない状態です。**",
              file=sys.stderr)
        return 2
    try:
        conf = json.loads(args.config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"設定が読めません: {args.config}: {e}", file=sys.stderr)
        return 2
    base = args.root.resolve()
    exp = base / conf.get("export", "design/figma/components.json")
    if not exp.exists():
        print(f"書き出しがありません: {exp}", file=sys.stderr)
        return 2
    try:
        doc = json.loads(exp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"書き出しが読めません: {exp}: {e}", file=sys.stderr)
        return 2

    errs = []
    holes = variant_holes(doc)
    declared = conf.get("declaredHoles") or {}
    for name, h in holes.items():
        why = declared.get(name)
        if isinstance(why, str) and why.strip():
            continue
        errs.append(f"  **穴のある component set**: {name}\n"
                    f"    軸 {h['axes']} / あるもの {h['あるもの']} / "
                    f"総当たり {h['総当たり']}\n"
                    f"    欠け: {' / '.join(h['欠け'][:6])}"
                    + ("…" if len(h["欠け"]) > 6 else "") + "\n"
                    f"    **実装がこの組み合わせへ動きうるなら落ちます。**\n"
                    f"    動かないなら {args.config.name} の declaredHoles に"
                    f"理由を書いてください。")

    # 状態の軸を持つ部品の名前を、書き出しから導出する
    sets = doc.get("componentSets") or doc
    stateful = []
    for name, v in (sets.items() if isinstance(sets, dict) else []):
        if not isinstance(v, dict):
            continue
        axes, _rows = variant_rows(v)
        if axes and any(a in STATE_AXES for a in axes):
            stateful.append(name)

    tdir = base / conf.get("tests", "test")
    weak = tests_without_hold(tdir, stateful)
    if weak is None:
        errs.append(f"  検査の置き場がありません: {tdir}")
    else:
        for f, names in weak:
            errs.append(f"  {f.relative_to(base)}: 状態の軸を持つ部品"
                        f"（{' / '.join(names)}）を `tap` だけで触っています。\n"
                        f"    **`tap` は down と up の間にフレームを挟まないので、"
                        f"押した見た目が一度も描かれません。**\n"
                        f"    `startGesture` + `pump` を1回以上入れてください。")

    if errs:
        print(f"押した状態が見られていません（状態の軸を持つ部品 "
              f"{len(stateful)} 件）:", file=sys.stderr)
        print("\n".join(errs[:20]), file=sys.stderr)
        return 1
    print(f"押した状態: 状態の軸を持つ部品 {len(stateful)} 件、"
          f"穴のある set {len(holes)} 件（宣言済み）。試験は押しっぱなしを"
          f"使っています。")
    return 0


def self_test():
    import contextlib
    import io
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "design" / "figma").mkdir(parents=True)
        (root / "test").mkdir()
        exp = root / "design" / "figma" / "components.json"
        cp = root / "design" / "interaction.json"
        tf = root / "test" / "nav_test.dart"

        FULL = {"componentSets": {"Nav": {"componentVariantList": [
            ["Selected", "State"],
            ["False|Enabled", "False|Pressed", "True|Enabled", "True|Pressed"]]}}}
        HOLED = {"componentSets": {"Nav": {"componentVariantList": [
            ["Selected", "State"],
            ["False|Enabled", "False|Pressed", "True|Enabled"]]}}}

        def run(doc, test_src, conf=None):
            exp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            tf.write_text(test_src, encoding="utf-8")
            cp.write_text(json.dumps(conf or {"export": "design/figma/components.json",
                                              "tests": "test"}, ensure_ascii=False),
                          encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = main(["--config", str(cp), "--root", str(root)])
            return rc, buf.getvalue()

        HOLD = ("testWidgets('x', (t) async {\n"
                "  await t.pumpWidget(Nav());\n"
                "  final g = await t.startGesture(t.getCenter(find.byType(Nav)));\n"
                "  await t.pump(const Duration(milliseconds: 60));\n"
                "  await g.up();\n});\n")
        TAPONLY = ("testWidgets('x', (t) async {\n"
                   "  await t.pumpWidget(Nav());\n"
                   "  await t.tap(find.byType(Nav));\n});\n")

        rc, out = run(FULL, HOLD)
        if rc != 0:
            print(f"self-test NG: 穴も無く押しっぱなしもあるのに落ちた（{rc}）"
                  f"\n   {out[:300]}"); ok = False

        # **tap だけの試験は落ちる**（#27）
        rc, out = run(FULL, TAPONLY)
        if rc != 1 or "押した見た目が一度も描かれません" not in out:
            print(f"self-test NG: tap だけの試験を通した（{rc}）"); ok = False

        # **穴のある set は落ちる**（#28）
        rc, out = run(HOLED, HOLD)
        if rc != 1 or "True|Pressed" not in out:
            print(f"self-test NG: 穴を見逃した（{rc}）\n   {out[:300]}"); ok = False
        # 理由つきで宣言すれば通る
        rc, out = run(HOLED, HOLD, {"export": "design/figma/components.json",
                                    "tests": "test",
                                    "declaredHoles": {
                                        "Nav": "選ばれたタブに押した見た目は要らない"}})
        if rc != 0:
            print(f"self-test NG: 宣言があるのに落ちた（{rc}）\n   {out[:300]}")
            ok = False
        rc, _ = run(HOLED, HOLD, {"export": "design/figma/components.json",
                                  "tests": "test", "declaredHoles": {"Nav": "  "}})
        if rc != 1:
            print("self-test NG: 理由が空の宣言を通した"); ok = False

        # 状態の軸を持たない部品の試験は咎めない
        NOSTATE = {"componentSets": {"Card": {"componentVariantList": [
            ["Style"], ["Neutral", "Accent"]]}}}
        rc, out = run(NOSTATE, TAPONLY)
        if rc != 0:
            print(f"self-test NG: 状態の軸が無い部品で咎めた（{rc}）"); ok = False

        # 設定が無ければ落ちる
        cp.unlink()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            if main(["--config", str(cp), "--root", str(root)]) != 2:
                print("self-test NG: 設定が無いのに通した"); ok = False
    # コメントの中だけに部品名がある試験は、その部品を「触っている」に数えない
    import tempfile as _tf
    with _tf.TemporaryDirectory() as td2:
        d = Path(td2); (d / "t").mkdir()
        (d / "t" / "c_test.dart").write_text(
            "// Images が 8 を 16 にしていた\n"
            "await tester.tap(find.text('トークン'));\n", encoding="utf-8")
        if tests_without_hold(d / "t", ["Images"]):
            print("self-test NG: コメントだけの言及を『触っている』と数えた"); ok = False
        (d / "t" / "c_test.dart").write_text(
            "await tester.tap(find.byType(Images));\n", encoding="utf-8")
        if not tests_without_hold(d / "t", ["Images"]):
            print("self-test NG: コードで tap しているのを見逃した"); ok = False

    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
