#!/usr/bin/env python3
"""種まき欠陥テスト: この案件のルールが**実際に発火するか**を見る（2026-08-29 新設）。

## 妨害テストとの違い（層が1つ上）

| | 数えるもの | 捕まえる失敗 |
|---|---|---|
| `attack/engine_attack_test.py` | エンジンの挙動 | エンジンが壊れた |
| `expected_targets`（ラチェット） | **読んだファイル数** | 検査対象が黙って狭まった |
| **この検査** | **ルールごとの発火件数** | **ルールが黙って死んだ** |

ファイルは全部読んでいるのに、ルールが1件も当たらない——これは上の2つを素通りする。

実害:

- **aub の `require-semantics-on-tappable`**: 幽霊ルールだった。SKILL.md にも
  rules.json にも書いてあるのに実装がどこにも無く、**一度も走っていなかった**。
  種まきがあれば初日に赤くなっていた（「seed に違反があるのに0件」）
- **正規表現の微妙なズレ**: `Color\\(0x…\\)` を見るルールは `Color.fromARGB(...)` を
  拾わない。エンジンは正常・ルールも「実行可能」・しかし永遠に0件で緑

同じ発想が drift-lab（`node audit.mjs reference` は 100% と出なければ計測器が壊れている）
と orimoaides のシード欠陥検出テスト 8/8 にある。

## 置き方（案件のルートで）

    design/seeds/
      seed_no_raw_color.dart          # そのルールの違反を意図的に書く
      seed_no_raw_edgeinsets.dart
      expected.json                   # {"no-raw-color": 1, "no-raw-edgeinsets": 1}

**seeds は通常の走査から必ず除外する**（rules.json の exclude_paths に
`design/seeds/` を入れる）。この検査は除外を無視して seeds だけを直接読む。

`expected.json` の `"*"` に真を入れると、**rules に載っている全ルールが
expected に現れることを要求する**（種を書き忘れたルールを検出する）。

## 使い方

    python3 design/harness/tools/seed_check.py [--seeds design/seeds] [--rules design/rules.json]

## この検査が捕まえないもの

- 正規表現が**広すぎる**こと（本物のコードでの誤検出）。それは実運用と warn が見る
- 宣言に無いキー・rules.json に無い id は**落とす**（黙って捨てない・aub 提案9）
- ルールの内容が正しいか（禁止すべきものを禁止しているか）。それは人が決める
- 確かめた方法: --self-test（ルールを壊したら落ちること・種の書き忘れで落ちること）
"""

import argparse
import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent / "engine" / "design_check.py"


def load_engine(path=ENGINE):
    spec = importlib.util.spec_from_file_location("_engine", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def count_hits(engine, config, seeds_dir, project_root):
    """seeds の各ファイルを走査し、ルールごとの発火件数を数える。

    is_target を通さない（seeds は除外設定に入っているのが正しいため）。
    """
    counts, read = {}, []
    for f in sorted(seeds_dir.rglob("*")):
        if not f.is_file() or f.name == "expected.json":
            continue
        try:
            content = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            print(f"種が読めません: {f}: {e.__class__.__name__}", file=sys.stderr)
            return None, []
        read.append(f)
        _, _, obs = engine.scan(content, config, f, project_root)
        for o in obs:
            if o.get("kind") == "hit":
                counts[o["rule"]] = counts.get(o["rule"], 0) + 1
    return counts, read


def main(argv=None):
    ap = argparse.ArgumentParser(description="ルールが実際に発火するか（種まき）")
    ap.add_argument("--seeds", type=Path, default=Path("design/seeds"))
    ap.add_argument("--rules", type=Path, default=Path("design/rules.json"))
    ap.add_argument("--engine", type=Path, default=ENGINE)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    if not args.seeds.exists():
        print(f"種の置き場がありません: {args.seeds}\n"
              f"  ルールが実際に発火するかを誰も確かめていない状態です。\n"
              f"  各ルールの違反を1件ずつ書いたファイルと expected.json を置いてください。",
              file=sys.stderr)
        return 2

    engine = load_engine(args.engine)
    config = engine.load_rules(args.rules)
    if not config:
        print(f"ルールが読めません: {args.rules}", file=sys.stderr)
        return 2

    exp_path = args.seeds / "expected.json"
    if not exp_path.exists():
        print(f"{exp_path} がありません（何件出るはずかの宣言が要ります）",
              file=sys.stderr)
        return 2
    expected = json.loads(exp_path.read_text(encoding="utf-8"))
    require_all = bool(expected.pop("*", False))
    expected = {k: v for k, v in expected.items() if not k.startswith("$")}

    project_root = args.rules.resolve().parent.parent
    counts, read = count_hits(engine, config, args.seeds, project_root)
    if counts is None:
        return 2
    if not read:
        print(f"種のファイルが1つもありません: {args.seeds}（空振り）", file=sys.stderr)
        return 1

    declared_ids = {r.get("id") for r in config.get("rules", []) if r.get("id")}

    problems = []
    for rid, want in sorted(expected.items()):
        got = counts.get(rid, 0)
        # 台帳が知らないキーを黙って扱わない（aub 提案9・2026-08-29）。
        # rules.json に無い id を「死んでいる」と報告すると、綴り間違いが
        # 「ルールの不具合」に化けて、直す場所を間違える
        if rid not in declared_ids:
            problems.append(
                f"{rid}: expected.json にあるが **rules.json に無いルール**です。"
                f"綴りを確かめるか、宣言から消してください"
                f"（似ている id: {', '.join(sorted(declared_ids)[:3])}…）")
            continue
        if got != want:
            problems.append(
                f"{rid}: {want}件出るはずが {got}件"
                + ("  ← **このルールは死んでいます**（種に違反があるのに発火しない）"
                   if got == 0 else ""))
    for rid, got in sorted(counts.items()):
        if rid not in expected:
            problems.append(f"{rid}: 宣言に無いのに {got}件発火しました"
                            f"（種が別のルールにも当たっています。expected.json に足すか種を分けてください）")

    if require_all:
        declared = {r.get("id") for r in config.get("rules", []) if r.get("id")}
        missing = sorted(declared - set(expected))
        if missing:
            problems.append("種が書かれていないルール: " + " / ".join(missing)
                            + "（expected.json の \"*\" が真なので全ルールに種が要ります）")

    print(f"種まき欠陥テスト: {len(read)}ファイル / "
          f"{len(expected)}ルールを宣言 / {sum(counts.values())}件発火")
    if problems:
        print("\nルールが宣言どおりに発火していません:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print(f"  OK: 宣言した{len(expected)}ルールがすべて宣言どおりの件数で発火しました。")
    return 0


def self_test():
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "design" / "seeds").mkdir(parents=True)
        rules = root / "design" / "rules.json"
        seeds = root / "design" / "seeds"

        def write_rules(color_pat=r"Color\(0x[0-9A-Fa-f]{8}\)"):
            rules.write_text(json.dumps({
                "file_extensions": [".dart"],
                "rules": [
                    {"id": "no-raw-color", "severity": "error", "pattern": color_pat},
                    {"id": "no-raw-fontsize", "severity": "error",
                     "pattern": r"fontSize:\s*[0-9]"},
                ]}), encoding="utf-8")

        write_rules()
        (seeds / "seed_color.dart").write_text(
            "final c = Color(0xFF3B82F6);\n", encoding="utf-8")
        (seeds / "seed_fontsize.dart").write_text(
            "const s = TextStyle(fontSize: 14);\n", encoding="utf-8")
        exp = seeds / "expected.json"
        argv = ["--seeds", str(seeds), "--rules", str(rules)]

        exp.write_text(json.dumps({"no-raw-color": 1, "no-raw-fontsize": 1}),
                       encoding="utf-8")
        if main(argv) != 0:
            print("self-test NG: 宣言どおりなのに落ちた"); ok = False

        # ルールを壊す（正規表現を実在しない書き方に変える）→ 落ちること（本体）
        write_rules(r"Color\.fromARGB\(")
        if main(argv) != 1:
            print("self-test NG: ルールが死んでいるのに落ちなかった"); ok = False
        write_rules()

        # rules.json に無い id を宣言している（綴り間違い）
        exp.write_text(json.dumps({"no-raw-color": 1, "no-raw-fontsize": 1,
                                   "no-raw-colour": 1}), encoding="utf-8")
        if main(argv) != 1:
            print("self-test NG: rules.json に無い id を見逃した"); ok = False

        # 種を書き忘れる（"*" が真のとき）
        exp.write_text(json.dumps({"*": True, "no-raw-color": 1}), encoding="utf-8")
        if main(argv) != 1:
            print("self-test NG: 種の書き忘れを見逃した"); ok = False

        # 宣言より多く出る
        exp.write_text(json.dumps({"no-raw-color": 1, "no-raw-fontsize": 1}),
                       encoding="utf-8")
        (seeds / "seed_extra.dart").write_text(
            "final d = Color(0xFF000000);\n", encoding="utf-8")
        if main(argv) != 1:
            print("self-test NG: 宣言より多いのに落ちなかった"); ok = False
        (seeds / "seed_extra.dart").unlink()

        # 種が空（空振り）
        for f in seeds.glob("*.dart"):
            f.unlink()
        if main(argv) != 1:
            print("self-test NG: 種が空なのに落ちなかった"); ok = False

        # 宣言（expected.json）が無い・置き場が無い＝検査が働いていない（2）。
        # 違反（1）と区別する（変異試験 2026-09-05 で、この2本は一度も通っていなかった）
        exp.unlink()
        if main(argv) != 2:
            print("self-test NG: expected.json が無いのに 2 で止まらなかった"); ok = False
        if main(["--seeds", str(root / "nope"), "--rules", str(rules)]) != 2:
            print("self-test NG: 種の置き場が無いのに 2 で止まらなかった"); ok = False

    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
