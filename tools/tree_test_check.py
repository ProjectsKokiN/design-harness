#!/usr/bin/env python3
"""条件9（見本と相互作用）の網羅を、書き出しから導いて見る（2026-08-29 新設）。

## 実害（aub-familywalk 2026-08-29）

> Figma に **8セットぶん**の `Hovered` / `Pressed` があるのに、駆動するものがゼロ。
> **「描ける」で完成と見なしていた**。バリアントは全部揃っているので網羅の検査は通った

値も網羅も緑のまま、押しても何も起きない部品ができます。
**分母を Figma の書き出しから機械的に出す**のが要点です（条件7と同じ形）。

## 見るもの

書き出しの `componentSets` から分母を出し、対応するテストが在るかを見ます。

| 導く条件 | 分母の出し方 | 何を要求するか |
|---|---|---|
| 9-4 相互作用 | 状態（Hovered / Pressed / Focused）を含むセット | そのセット名を参照するテスト |
| 9-2 見本の子 | `slots` を2つ以上持つセット | 同上 |

**テストの中身は見ません。**「在るか」だけです（条件7が実装の有無だけ見るのと同じ）。
中身の質は人と `agent-review` の領域。

## 捕まえないもの

- テストが**正しく**書けているか。名前を出しただけのテストも通る
  （照合はセット名の**完全一致**。先頭名まで許すと関門が緩む）
- 9-1（重なり順）と 9-3（軸）。これは木と生成の中身の話で、**案件のテストが直に見る**
- 確かめた方法: --self-test（分母が出るのにテストが無いと落ちること・空振りで落ちること）

## 使い方（案件のルートで）

    python3 design/harness/tools/tree_test_check.py --config design/tree-tests.json

    {
      "export": "design/figma/components.json",
      "test_dirs": ["test"],
      "state_words": ["Hovered", "Pressed", "Focused"],
      "min_slots": 2,
      "allow": [{"set": "Lists/Subtle", "why": "表示専用。押せる要素を持たない"}]
    }
"""

import argparse
import json
import re
import sys
from pathlib import Path

SUFFIXES = (".dart", ".ts", ".tsx", ".js", ".mjs", ".py")
DEFAULT_STATES = ["Hovered", "Pressed", "Focused"]


def load_sets(doc):
    cs = doc.get("componentSets")
    if isinstance(cs, dict):
        return cs
    if isinstance(cs, list):
        return {c.get("name"): c for c in cs if isinstance(c, dict) and c.get("name")}
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description="条件9 の網羅（書き出しから導く）")
    ap.add_argument("--config", type=Path, default=Path("design/tree-tests.json"))
    ap.add_argument("--root", type=Path)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    if not args.config.exists():
        print(f"設定がありません: {args.config}\n"
              f"  Figma に状態があるのに駆動していない部品を、誰も見ていない状態です。",
              file=sys.stderr)
        return 1
    conf = json.loads(args.config.read_text(encoding="utf-8"))
    base = (args.root.resolve() if args.root
            else args.config.resolve().parent.parent)

    ex = base / conf.get("export", "design/figma/components.json")
    if not ex.exists():
        print(f"書き出しがありません: {ex}\n"
              f"  **分母が無いので網羅を確かめられません。**", file=sys.stderr)
        return 1
    sets = load_sets(json.loads(ex.read_text(encoding="utf-8")))
    if sets is None:
        print(f"{ex} に componentSets がありません（形が変わった可能性）",
              file=sys.stderr)
        return 2
    if not sets:
        print(f"{ex} の componentSets が空です。**『穴 0』は『何も見ていない』"
              f"という意味です。**", file=sys.stderr)
        return 1

    states = conf.get("state_words") or DEFAULT_STATES
    state_rx = re.compile("|".join(re.escape(s) for s in states), re.I)
    min_slots = int(conf.get("min_slots", 2))

    allow, problems = {}, []
    for a in conf.get("allow", []):
        if not isinstance(a, dict) or not a.get("why"):
            problems.append(f"allow の「{a}」に why がありません")
            continue
        allow[a["set"]] = a["why"]

    need = {}
    for name, v in sets.items():
        blob = json.dumps(v, ensure_ascii=False)
        why = []
        if state_rx.search(blob):
            why.append("状態を持つ（9-4）")
        slots = v.get("slots")
        if isinstance(slots, (list, dict)) and len(slots) >= min_slots:
            why.append(f"スロットが{len(slots)}つ（9-2）")
        if why:
            need[name] = " / ".join(why)

    blob = ""
    for d in conf.get("test_dirs") or ["test"]:
        dp = base / d
        if not dp.exists():
            problems.append(f"テストの置き場がありません: {d}")
            continue
        for f in sorted(dp.rglob("*")):
            if f.is_file() and f.suffix in SUFFIXES:
                blob += f.read_text(encoding="utf-8", errors="ignore") + "\n"

    missing, allowed = [], []
    for name, why in sorted(need.items()):
        if name in allow:
            allowed.append(f"{name}（{allow[name]}）")
            continue
        # **セット名そのもの**で照合する。先頭の部品名（Buttons/M/Default →
        # Buttons）まで許すと、名前が似た別のテストで通ってしまい、関門が緩む。
        # aub の実データでは対象17セット全部が完全名で一致した（2026-08-29）ので、
        # 厳密にしても実運用の負担にならないことを確認済み
        if name in blob:
            continue
        missing.append(f"{name} — {why}")

    print(f"条件9 の網羅: 書き出しの{len(sets)}セット中 {len(need)}セットが対象 / "
          f"テスト在り {len(need) - len(missing) - len(allowed)} / "
          f"例外 {len(allowed)} / 無し {len(missing)}")
    for a in allowed:
        print(f"  例外: {a}")
    if missing:
        problems.append(
            "対象なのにテストが見当たらないセット:\n      "
            + "\n      ".join(missing)
            + "\n      **「描ける」は完成ではありません。**押して切り替わるか・"
              "子を全部渡しているかを、木と数で確かめるテストを書いてください")

    if problems:
        print("\n条件9 の網羅に穴があります:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    return 0


def self_test():
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "design" / "figma").mkdir(parents=True)
        (root / "test").mkdir()
        cfg = root / "design" / "tree-tests.json"
        ex = root / "design" / "figma" / "components.json"
        argv = ["--config", str(cfg), "--root", str(root)]

        def setup(sets, tests=None, allow=None):
            ex.write_text(json.dumps({"componentSets": sets}), encoding="utf-8")
            for f in (root / "test").glob("*"):
                f.unlink()
            for n, b in (tests or {}).items():
                (root / "test" / n).write_text(b, encoding="utf-8")
            cfg.write_text(json.dumps({"export": "design/figma/components.json",
                                       "test_dirs": ["test"],
                                       "allow": allow or []}), encoding="utf-8")

        setup({"Buttons/M": {"variants": ["Hovered", "Pressed"]},
               "Plain/X": {"variants": ["Default"]}})
        if main(argv) != 1:
            print("self-test NG: 状態があるのにテストが無いのに通した"); ok = False

        setup({"Buttons/M": {"variants": ["Hovered"]}, "Plain/X": {}},
              tests={"t.dart": "testWidgets('Buttons/M hover', ...);\n"})
        if main(argv) != 0:
            print("self-test NG: 完全名で参照するテストがあるのに落ちた"); ok = False

        # 先頭名だけのテストでは通さない（照合が緩んでいないこと）
        setup({"Buttons/M": {"variants": ["Hovered"]}},
              tests={"t.dart": "testWidgets('Buttons hover', ...);\n"})
        if main(argv) != 1:
            print("self-test NG: 先頭名だけのテストで通してしまった"); ok = False

        setup({"Buttons/M": {"variants": ["Hovered"]}},
              allow=[{"set": "Buttons/M", "why": "表示専用"}])
        if main(argv) != 0:
            print("self-test NG: 理由つきの例外で落ちた"); ok = False
        setup({"Buttons/M": {"variants": ["Hovered"]}},
              allow=[{"set": "Buttons/M"}])
        if main(argv) != 1:
            print("self-test NG: 理由の無い例外を通した"); ok = False

        setup({"Footer": {"slots": ["Top", "Bottom"]}})
        if main(argv) != 1:
            print("self-test NG: スロット2つのセットを見逃した"); ok = False

        setup({})
        if main(argv) != 1:
            print("self-test NG: 書き出しが空なのに落ちなかった"); ok = False

        ex.unlink()
        if main(argv) != 1:
            print("self-test NG: 書き出しが無いのに落ちなかった"); ok = False

    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
