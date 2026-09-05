#!/usr/bin/env python3
"""照合テストの期待値が書き出し由来かを見る（aub 提案3・2026-08-29）。

## 実害

> 期待値を手で書き、**実装と同じ思い込み**になっていた（Switches の重なり順・aub）

手書きの期待値は、実装を書いた本人（AI）が書きます。**実装が間違っていれば
期待値も同じように間違い、テストは一致して通ります。** 自分の答案の自己採点で、
記録層を廃止したのと同じ構図です。

## 見るもの

**照合テストの置き場（既定 `test/design/`）のファイルは、書き出しを読んでいること。**

- `figma/*.json`（または config の `export_globs` に合う名前）を読む記述があるか
- 無ければ「手書きの期待値」として落とす
- 例外は `allow` に**理由と棚卸しの期限つきで**宣言する
  （理由・期限の無い例外、期限切れの例外は落とす）

## この検査が捕まえないもの

- 書き出しを読んだうえで**読み方を間違えている**こと。それは照合テスト自身の領域
- 照合テストの置き場の外に書いた手書き期待値。**置き場の宣言は案件の責任**
- 「読んでいる」の判定は文字列の出現。動的に組み立てたパスは見えない
- 確かめた方法: --self-test（書き出しを読まないテストを置くと落ちること）

## 使い方（案件のルートで）

    python3 design/harness/tools/expectation_source_check.py \\
        --config design/expectations.json

    {
      "dirs": ["test/design"],
      "export_globs": ["figma/", "design/figma/", "frames.json", "components.json"],
      "allow": [
        {"file": "test/design/smoke_test.dart", "why": "期待値を持たない起動確認"}
      ]
    }
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

TODAY = date.today().isoformat()

SUFFIXES = (".dart", ".ts", ".tsx", ".js", ".mjs", ".py")
DEFAULT_GLOBS = ["figma/", "design/figma/", "frames.json", "components.json",
                 "variables.json", "styles.json"]


def main(argv=None):
    ap = argparse.ArgumentParser(description="照合テストの期待値が書き出し由来か")
    ap.add_argument("--config", type=Path, default=Path("design/expectations.json"))
    ap.add_argument("--root", type=Path)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    if not args.config.exists():
        print(f"設定がありません: {args.config}\n"
              f"  照合テストの期待値がどこ由来かを、誰も見ていない状態です。\n"
              f'  {{"dirs": ["test/design"]}} から始めてください。', file=sys.stderr)
        return 2
    try:
        conf = json.loads(args.config.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"設定が読めません: {args.config}: {e}", file=sys.stderr)
        return 2

    base = (args.root.resolve() if args.root
            else args.config.resolve().parent.parent)
    globs = conf.get("export_globs") or DEFAULT_GLOBS
    allow = {}
    problems = []
    for a in conf.get("allow", []):
        if isinstance(a, str):
            problems.append(f"allow の「{a}」に理由（why）がありません。"
                            f'{{"file": …, "why": …}} の形で書いてください')
            allow[a] = None
        else:
            f_, why, by = a.get("file"), a.get("why"), a.get("reviewBy")
            if not why:
                problems.append(f"allow の「{f_}」に why がありません")
            if not by:
                problems.append(f"allow の「{f_}」に reviewBy がありません"
                                f"（例外は期限つきにする）")
            elif by < TODAY:
                problems.append(
                    f"allow の「{f_}」は期限（{by}）を過ぎています。"
                    f"**書き出しから読むように直すか、理由がまだ生きているか"
                    f"確かめてください**")
            allow[f_] = f"{why or '理由なし'} / 期限 {by or '未設定'}"

    dirs = conf.get("dirs") or []
    if not dirs:
        print(f"{args.config} に dirs がありません（照合テストの置き場の宣言）",
              file=sys.stderr)
        return 2

    checked, handwritten, allowed = 0, [], []
    for d in dirs:
        dp = base / d
        if not dp.exists():
            problems.append(f"照合テストの置き場がありません: {d}"
                            f"（宣言だけあって実体が無い状態）")
            continue
        for f in sorted(dp.rglob("*")):
            if not f.is_file() or f.suffix not in SUFFIXES:
                continue
            rel = f.relative_to(base).as_posix()
            checked += 1
            if rel in allow:
                allowed.append(f"{rel}（{allow[rel] or '理由なし'}）")
                continue
            text = f.read_text(encoding="utf-8", errors="ignore")
            if not any(g in text for g in globs):
                handwritten.append(rel)

    print(f"期待値の出どころ: {checked}ファイル中 "
          f"{checked - len(handwritten) - len(allowed)}件が書き出しを読んでいます")
    for a in allowed:
        print(f"  例外: {a}")
    if handwritten:
        problems.append(
            "書き出しを読んでいない照合テスト（手書きの期待値）:\n      "
            + "\n      ".join(handwritten)
            + "\n      **実装を書いた本人が期待値も書くと、同じ思い込みで一致します。**"
              "\n      書き出しから読むか、期待値を持たないなら allow に理由つきで宣言してください")
    if checked == 0:
        problems.append(f"照合テストが1件もありません（{dirs}）。空振りです")

    if problems:
        print("\n期待値の出どころが確かめられていません:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print("  OK: 照合テストはすべて書き出しを読んでいます。")
    return 0


def self_test():
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "design").mkdir()
        (root / "test" / "design").mkdir(parents=True)
        cfg = root / "design" / "expectations.json"

        def setup(files, allow=None):
            for n, body in files.items():
                (root / "test" / "design" / n).write_text(body, encoding="utf-8")
            cfg.write_text(json.dumps({"dirs": ["test/design"],
                                       "allow": allow or []}), encoding="utf-8")
            return ["--config", str(cfg), "--root", str(root)]

        for f in (root / "test" / "design").glob("*"):
            f.unlink()
        if main(setup({"a_test.dart":
                       "final doc = File('design/figma/frames.json');\n"})) != 0:
            print("self-test NG: 書き出しを読むテストで落ちた"); ok = False

        if main(setup({"b_test.dart": "expect(height, 148);\n"})) != 1:
            print("self-test NG: 手書きの期待値を見逃した"); ok = False

        if main(setup({}, allow=[{"file": "test/design/b_test.dart",
                                  "why": "期待値を持たない",
                                  "reviewBy": "2099-01-01"}])) != 0:
            print("self-test NG: 理由と期限つきの例外で落ちた"); ok = False
        if main(setup({}, allow=[{"file": "test/design/b_test.dart"}])) != 1:
            print("self-test NG: 理由の無い例外を通した"); ok = False
        if main(setup({}, allow=[{"file": "test/design/b_test.dart",
                                  "why": "x"}])) != 1:
            print("self-test NG: 期限の無い例外を通した"); ok = False
        if main(setup({}, allow=[{"file": "test/design/b_test.dart",
                                  "why": "x", "reviewBy": "2020-01-01"}])) != 1:
            print("self-test NG: 期限切れの例外を通した"); ok = False

        for f in (root / "test" / "design").glob("*"):
            f.unlink()
        if main(setup({})) != 1:
            print("self-test NG: 照合テストが0件なのに落ちなかった"); ok = False

        # dirs の宣言が無い＝どこを見るかが決まらない（exit 2）
        cfg.write_text(json.dumps({"allow": []}), encoding="utf-8")
        if main(["--config", str(cfg), "--root", str(root)]) != 2:
            print("self-test NG: dirs が無いのに 2 で止まらなかった"); ok = False

        cfg.unlink()
        # 設定が無い＝検査が働いていない（exit 2）。違反（exit 1）と区別する
        if main(["--config", str(cfg), "--root", str(root)]) != 2:
            print("self-test NG: 設定が無いのに 2 で止まらなかった"); ok = False

    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
