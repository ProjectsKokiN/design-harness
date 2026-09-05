#!/usr/bin/env python3
"""照合体制の検査（**参考**。関門の条件ではない）。

**2026-09-03、ユーザーの指示で条件2 は廃止しました。** 原文は「条件2は廃止で」。
関門は 1・4・5・7・8・9 の6つ（`production-gate.md` が正本）。

**この道具は消しません。** 廃止したのは「関門で機械的に落とす」ところだけで、
検査としては有用です。ただし**落ちてもリリースは止まりません。**

廃止しても残る危険（記録）: **AI が手で書いた期待値は、自分の答案の自己採点に
なる。** aub の実測で「検査は緑なのに Figma と違う」誤り8件は全部が手書きの層から
出ており、機械生成の層は 0 件でした。

**照合相手は Figma の機械書き出し（figma/*.json）だけ。手で書いた記録層
（design/values/）は照合相手にしない**（2026-08-29 ユーザー確定:
「実装と記録を見比べる必要はないです。実装と Figma を見比べればいいです」）。

旧実装は「values ファイルとテストが在るか」を数えていた——つまり
**AI が手で書いた記録**との照合率だった。aub-familywalk の実測で、
検査が緑のまま Figma と違っていた誤り8件の全部が手書きの層から出た
（機械生成の層は0件）。記録を書いたのも AI なので、自分の答案を自分で
採点している状態だった。

## 測り方（この検査は「体制」を見る）

実装値が書き出しと突き合っている状態は、次の合成で成立する:

  (a) 生値の直書きが 0            … design_check.py（既存）
  (b) 生成器の入力が書き出しだけ  … gen_input_check.py（2026-08-29 新設）
  (c) 生成物が書き出しと一致      … design/gen/verify.py（べき等性・案件側）
  (d) 部品が数値を自分で持たない  … component_spec 検査（案件側）
  (e) 画面固有の値は frames.json を読む照合テストが見る

この検査が機械で見るのは、その体制が壊れていないこと:

  1. 記録層（design/values/）が照合に使われていないか（移行検査）
  2. 生成器の道があるか（design/gen/verify.py の存在）
  3. 画面照合の行き先（figma/frames.json）があるか
  4. figma/ の書き出し一式がそろっているか

## この検査が捕まえないもの

- **照合の質**（値が本当に一致しているか）。それは (c) のべき等性検査と
  案件の照合テストの領域。この検査は配線を見る
- 個々の画面が frames.json と照合済みかの網羅（第2段。列挙型テストの
  出力形式が決まってから機械化する。それまで残数は手で報告する）
- 確かめた方法: --self-test（記録層を仕込んで落ちること）

## 使い方（案件のルートで）

    python3 design/harness/tools/coverage_check.py --config coverage.json

coverage.json（パスは config からの相対）:

    {
      "figma_dir": "../<ds>/figma",
      "values_dir": "design/values",
      "gen_dir": "design/gen",
      "fail_on_values": false
    }

- `fail_on_values`: 新規案件は **true**（記録層が存在した時点で落ちる）。
  既存案件（FlashEnglish / planttalk / qnd-database）は false で移行猶予。
  **移行の確認は、ユーザーがその案件を再開するときに行う**（2026-08-29 確定）。
  猶予中も残数（記録ファイル数）を毎回表示する
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

REQUIRED_EXPORTS = ("components.json", "variables.json", "styles.json")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="照合体制の検査（参考。条件2 は廃止済み）")
    ap.add_argument("--config", type=Path)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()
    if not args.config:
        ap.error("--config が要ります（--self-test を除く）")

    try:
        conf = json.loads(args.config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"設定が読めません: {args.config}: {e}", file=sys.stderr)
        return 2
    base = args.config.resolve().parent
    figma_dir = base / conf.get("figma_dir", "design/figma")
    values_dir = base / conf.get("values_dir", "design/values")
    gen_dir = base / conf.get("gen_dir", "design/gen")
    fail_on_values = bool(conf.get("fail_on_values", True))

    problems, notes = [], []

    # 1) 記録層の移行状態
    leftovers = sorted(values_dir.glob("*.json")) if values_dir.exists() else []
    leftovers = [f for f in leftovers if f.name != "figma-missing.json"]
    if leftovers:
        msg = (f"記録層が {len(leftovers)} ファイル残っています"
               f"（照合相手は書き出しだけ・2026-08-29）: "
               f"{', '.join(f.name for f in leftovers[:6])}"
               f"{' …' if len(leftovers) > 6 else ''}")
        if fail_on_values:
            problems.append(msg)
        else:
            notes.append(msg + "\n    （移行猶予中。確認はユーザーが案件を再開するとき）")

    # 2) 書き出し一式
    if not figma_dir.exists():
        problems.append(f"書き出しがありません: {figma_dir}")
    else:
        missing = [n for n in REQUIRED_EXPORTS if not (figma_dir / n).exists()]
        if missing:
            problems.append(f"書き出しが欠けています: {missing}（{figma_dir}）")
        if not (figma_dir / "frames.json").exists():
            notes.append("figma/frames.json がありません。**画面固有の値の照合先が"
                         "無い**状態です（記録層の廃止は frames.json が前提）")

    # 3) 生成器の道
    if gen_dir.exists():
        if not (gen_dir / "verify.py").exists():
            problems.append(f"{gen_dir}/verify.py がありません"
                            f"（生成物が書き出しと一致するかを誰も見ていません）")
    else:
        notes.append(f"{gen_dir} がありません。トークン・部品仕様を書き出しから"
                     f"生成する道が無く、手で写す余地が残ります")

    print("照合体制（参考。条件2 は 2026-09-03 に廃止）:")
    for n in notes:
        print(f"  注意: {n}")
    if problems:
        print("\n体制が壊れています:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    if not notes:
        print("  OK: 照合相手は書き出しだけで、生成の道と画面照合の行き先があります。")
    else:
        print("  （注意ありで通過。残数は上のとおり）")
    return 0


def self_test():
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        figma = base / "figma"
        figma.mkdir()
        for n in REQUIRED_EXPORTS + ("frames.json",):
            (figma / n).write_text("{}", encoding="utf-8")
        gen = base / "design/gen"
        gen.mkdir(parents=True)
        (gen / "verify.py").write_text("", encoding="utf-8")

        def cfg(extra=None):
            d = {"figma_dir": "figma", "values_dir": "design/values",
                 "gen_dir": "design/gen", "fail_on_values": True}
            d.update(extra or {})
            (base / "c.json").write_text(json.dumps(d), encoding="utf-8")
            return ["--config", str(base / "c.json")]

        if main(cfg()) != 0:
            print("self-test NG: 体制がそろっているのに落ちた"); ok = False

        vals = base / "design/values"
        vals.mkdir()
        (vals / "header.json").write_text("{}", encoding="utf-8")
        if main(cfg()) != 1:
            print("self-test NG: 記録層が残っているのに落ちなかった"); ok = False
        if main(cfg({"fail_on_values": False})) != 0:
            print("self-test NG: 移行猶予なのに落ちた"); ok = False
        (vals / "header.json").unlink()

        (figma / "components.json").unlink()
        if main(cfg()) != 1:
            print("self-test NG: 書き出しが欠けているのに落ちなかった"); ok = False
        (figma / "components.json").write_text("{}", encoding="utf-8")

        (gen / "verify.py").unlink()
        if main(cfg()) != 1:
            print("self-test NG: verify.py が無いのに落ちなかった"); ok = False

    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
