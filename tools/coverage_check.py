#!/usr/bin/env python3
"""照合率の検査（production-gate の条件2）。planttalk の実装を 2026-08-28 に回収。

**Figma の全 component set・単体 component が、実測照合の対象になっているかを数える。**

なぜ要るか（production-gate.md より）: 「見ていないものが見えていない」を防ぐ。
flash-compose では 24 中 10 しか見ておらず、残りを足したらすぐ食い違いが出た。
どの案件にもこの検査が無く、条件2を測る道具が存在しなかった
（planttalk 第2便の提案2）。

## 何を「照合済み」と数えるか

values ファイルが存在し、かつそれを読むテストがあるものだけ。
**どちらか片方では数えない**（データだけあってテストが無いと、誰も比べていない）。

## この検査が捕まえないもの

**照合の「質」。** values とテストが在れば照合済みと数えるので、中身が薄くても
数は合う。**「照合率100%」を「Figma と一致」と読まないこと。**
確かめた方法: planttalk で穴16件を検出（26セット中10照合・2026-08-28）。

## 設定（--config で渡す coverage.json）

    {
      "export": "../design-systems/<名前>/figma/components.json",
      "values_dir": "design/values",
      "tests_dir": "test/ui",
      "test_glob": "*_values_test.dart",
      "fail_on_holes": true,
      "coverage": {
        "header": ["Header"],
        "chip": ["Chips/Default", "Chips/Outline"]
      }
    }

- パスはすべて **coverage.json からの相対**
- `fail_on_holes`: 新規案件は true（穴があれば exit 1）。既存案件は false で
  数だけ出し、リリース判断のときに残数を明記する（production-gate の段階適用）
- `coverage`: values ファイル名（拡張子なし）→ それが照合する Figma のセット名。
  対応表（component-map.json）に `values` キーが入るまでの置き場
"""

import argparse
import json
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description="照合率（production-gate 条件2）")
    ap.add_argument("--config", type=Path, required=True)
    args = ap.parse_args()

    try:
        conf = json.loads(args.config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"設定が読めません: {args.config}: {e}", file=sys.stderr)
        return 2
    base = args.config.resolve().parent
    export = base / conf["export"]
    values_dir = base / conf["values_dir"]
    tests_dir = base / conf["tests_dir"]
    test_glob = conf.get("test_glob", "*_values_test.dart")
    coverage = conf.get("coverage", {})
    fail_on_holes = bool(conf.get("fail_on_holes", True))

    if not export.exists():
        print(f"全量書き出しがありません: {export}", file=sys.stderr)
        return 2
    doc = json.loads(export.read_text(encoding="utf-8"))
    sets = set(doc.get("componentSets", {}))
    singles = set(doc.get("singleComponents", {}))
    excluded = set(doc.get("$meta", {}).get("excluded") or {})
    targets = (sets | singles) - excluded

    if not targets:
        print("NG: 照合対象が0件です（書き出しが空の可能性）", file=sys.stderr)
        return 2

    covered = set()
    incomplete = []
    for stem, names in coverage.items():
        has_values = (values_dir / f"{stem}.json").exists()
        # テストのファイル名は values の名前に揃っていないことがあるので、
        # 中身で values ファイルを参照しているテストを探す
        has_test = any(
            stem in t.read_text(encoding="utf-8", errors="ignore")
            for t in tests_dir.glob(test_glob)
        ) if tests_dir.exists() else False
        if has_values and has_test:
            covered.update(names)
        else:
            incomplete.append(
                f"{stem}: values={'あり' if has_values else '無し'} / "
                f"テスト={'あり' if has_test else '無し'}")

    unknown = sorted(covered - targets)
    holes = sorted(targets - covered)
    print(f"照合率: {len(targets) - len(holes)} / {len(targets)} セット")
    if excluded:
        print(f"  意図して外している: {len(excluded)} 件（{', '.join(sorted(excluded))}）")
    if incomplete:
        print("  片方しか無い組:")
        for i in incomplete:
            print(f"    {i}")
    if unknown:
        # 対応が実在しない名前を指していたら、それも嘘なので落とす
        # （aub 第1便の要望2: Figma に無い名前が対応表に書かれ「照合済みに見えて
        # つながっていない」状態が続いた）
        print(f"NG: coverage が Figma に無い名前を指しています: {unknown}",
              file=sys.stderr)
        return 1
    if holes:
        print(f"照合の穴が {len(holes)} 件あります:")
        for h in holes:
            print(f"  - {h}")
        if fail_on_holes:
            print("NG（fail_on_holes: true）", file=sys.stderr)
            return 1
        print("（fail_on_holes: false — 既存案件の段階適用。"
              "リリース判断にはこの残数を明記すること）")
        return 0
    print("OK: 照合の穴はありません")
    return 0


if __name__ == "__main__":
    sys.exit(main())
