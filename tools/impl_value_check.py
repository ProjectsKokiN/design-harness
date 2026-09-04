#!/usr/bin/env python3
"""実装の中だけの数値が、誰にも見られていないのを止める（2026-09-04 新設・#16 / #63）。

## 実害

**記録層（`design/values/*.json`）を消しても、手で測った値は消えません。
実装の定数へ移るだけです。**

| 案件 | 値 | 何が起きたか |
|---|---|---|
| aub | `82.4`（BINGO の型紙） | 390 で測った高さを固定で持っており、**440 の機体で5段ぶん 50px ずれた** |
| aub | `254`（板の高さ） | 紙が背高になると板が縦の真ん中に浮き、**上だけ余白が 20 → 45 に増えた** |
| aub | `138.0`（`statsHeight`） | コメントに **「Figma の実測。2026-08-31」** と書いてある |

`82.4` と `254` はユーザーが実機で見つけました。`138.0` は 2026-09-04 の
測定で見つかりました。**どれも、どの検査にも引っかかりません。**

| 道具 | 分母 | この値 |
|---|---|---|
| `screen_export_check` | 宣言した記録層のファイル | 実装の定数なので**外** |
| `expectation_source_check` | 照合テストが書き出しを読むか | 期待値ではないので**外** |
| `hollow_check` | 検査の書き方 | 実装なので**外** |
| 禁止パターン | 生値の直書き | トークンに無い画面固有の値は禁止できない |

**分母がどれも「Figma 側」か「検査側」で、実装側から見たものがありません。**

## 見るもの

    python3 tools/impl_value_check.py --config design/impl-values.json

実装（`lib/ui/**` など）が使っている数値とトークン名を拾い、
**書き出し（`figma/*.json`）と生成物のどちらにも無いもの**を出します。

無いものは**理由つきで宣言**させます（`design/off-figma.json`）。
動きの時間・ユーザーが実機で決めた値など、**正しく Figma に無いもの**はあります。
宣言があれば通り、無ければ落ちます。**「意図して無い」と「黙って焼き付いた」を
区別できる形にするのが目的**です。

## 捕まえないもの

- その値が**正しいか**。ここは「出どころがあるか」だけを見ます
- 実装の中で**派生した**値（`幅 - 20 * 2` のような式）。#16 の型紙はこの形で、
  **描かれた形を2つの幅で比べる**検査が別に要ります（#8 と同じ領域）
- 確かめた方法: --self-test（宣言の無い数値を1つ足すと落ちること）
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

#: 実装が使っている数値。2桁以上だけ見る（0〜9 は添字や真偽が混ざる）
NUM_RX = re.compile(r"(?<![\w.])(\d{2,}(?:\.\d+)?)(?![\w.])")
#: 実装が使っているトークン名。`AppColor.frameNeutralSubtle` の後ろ
TOKEN_RX = re.compile(r"\bApp[A-Z]\w*\.([a-zA-Z_]\w*)")
#: 行のコメント（この道具は「書いてある値」ではなく「使う値」を見る）
COMMENT_RX = re.compile(r"//.*")


def norm(n):
    """`350.0` と `350` を同じものとして扱う。"""
    return n.rstrip("0").rstrip(".") if "." in n else n


def corpus(paths):
    """書き出しと生成物の中身をひとまとめにする。"""
    blob = []
    for p in paths:
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and f.suffix in (".json", ".dart", ".ts", ".g.dart"):
                    blob.append(f.read_text(encoding="utf-8", errors="ignore"))
        elif p.exists():
            blob.append(p.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(blob)


def scan(impl_dirs, blob, suffixes):
    """実装が使っていて、出どころの無い数値とトークンを返す。"""
    nums_ok = set(NUM_RX.findall(blob))
    nums_ok |= {norm(n) for n in nums_ok}
    found = {}
    files = 0
    for d in impl_dirs:
        if not d.exists():
            continue
        for f in sorted(d.rglob("*")):
            if not f.is_file() or f.suffix not in suffixes:
                continue
            if f.name.endswith(".g.dart"):
                continue                       # 生成物は出どころそのもの
            files += 1
            text = COMMENT_RX.sub("", f.read_text(encoding="utf-8", errors="ignore"))
            miss_n = sorted({n for n in NUM_RX.findall(text)
                             if norm(n) not in nums_ok})
            miss_t = sorted({x for x in TOKEN_RX.findall(text) if x not in blob})
            if miss_n or miss_t:
                found[f] = (miss_n, miss_t)
    return found, files


def main(argv=None):
    ap = argparse.ArgumentParser(description="実装の中だけの数値を見つける")
    ap.add_argument("--config", type=Path, default=Path("design/impl-values.json"))
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    if not args.config.exists():
        print(f"設定がありません: {args.config}\n"
              f'  例: {{"impl": ["lib/ui"], "sources": ["design/figma", "lib/theme"],\n'
              f'        "suffixes": [".dart"], "declared": "design/off-figma.json"}}\n'
              f"  **実装の中だけの数値を、誰も見ていない状態です。**", file=sys.stderr)
        return 2
    try:
        conf = json.loads(args.config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"設定が読めません: {args.config}: {e}", file=sys.stderr)
        return 2
    base = args.root.resolve()
    impl = [base / p for p in conf.get("impl", ["lib/ui"])]
    sources = [base / p for p in conf.get("sources", ["design/figma"])]
    suffixes = tuple(conf.get("suffixes", [".dart"]))

    blob = corpus(sources)
    if not blob.strip():
        print(f"出どころが1つも読めません: "
              f"{', '.join(str(p) for p in sources)}\n"
              f"  **この状態の「出どころなし」は全部まちがいです。**", file=sys.stderr)
        return 2

    declared = {}
    dpath = conf.get("declared")
    if dpath and (base / dpath).exists():
        try:
            declared = json.loads((base / dpath).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"宣言が読めません: {base / dpath}: {e}", file=sys.stderr)
            return 2

    found, files = scan(impl, blob, suffixes)
    if files == 0:
        print(f"実装が1つもありません: {', '.join(str(p) for p in impl)}\n"
              f"  **0件は「綺麗」ではなく「見ていない」です。**", file=sys.stderr)
        return 2

    errs, waived = [], 0
    for f, (nums, toks) in sorted(found.items()):
        rel = str(f.relative_to(base))
        d = declared.get(rel, {})
        for n in nums:
            why = d.get(n) or d.get(norm(n))
            if isinstance(why, str) and why.strip():
                waived += 1
                continue
            errs.append(f"  {rel}: `{n}` の出どころがありません。\n"
                        f"    書き出しにも生成物にも無い数です。"
                        f"**Figma を直しても、ここは動きません。**")
        for x in toks:
            errs.append(f"  {rel}: トークン `{x}` が生成物にありません。")

    if errs:
        print(f"実装の中だけの数値があります（実装 {files} ファイル）:",
              file=sys.stderr)
        print("\n".join(errs[:30]), file=sys.stderr)
        if len(errs) > 30:
            print(f"  …ほか {len(errs) - 30} 件", file=sys.stderr)
        print(f"\n  正しく Figma に無いもの（動きの時間・実機で決めた値など）は、\n"
              f"  {dpath or 'design/off-figma.json'} に理由つきで宣言してください。",
              file=sys.stderr)
        return 1
    tail = f" / 理由つきの宣言 {waived}件" if waived else ""
    print(f"実装の中だけの数値: 0件（実装 {files} ファイル{tail}）。")
    return 0


def self_test():
    import contextlib
    import io
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "lib" / "ui").mkdir(parents=True)
        (root / "lib" / "theme").mkdir()
        (root / "design" / "figma").mkdir(parents=True)
        (root / "design" / "figma" / "frames.json").write_text(
            json.dumps({"frames": {"1:1": {"rows": ["0|A|FRAME|390|844|0|0"]}}}),
            encoding="utf-8")
        (root / "lib" / "theme" / "t.g.dart").write_text(
            "const gapM = 20.0;\nconst frameNeutralSubtle = 1;\n", encoding="utf-8")
        scr = root / "lib" / "ui" / "s.dart"
        cp = root / "design" / "impl-values.json"
        dp = root / "design" / "off-figma.json"
        cp.write_text(json.dumps({"impl": ["lib/ui"],
                                  "sources": ["design/figma", "lib/theme"],
                                  "suffixes": [".dart"],
                                  "declared": "design/off-figma.json"}),
                      encoding="utf-8")
        argv = ["--config", str(cp), "--root", str(root)]

        def run(src, decl=None):
            scr.write_text(src, encoding="utf-8")
            if decl is None:
                dp.unlink(missing_ok=True)
            else:
                dp.write_text(json.dumps(decl, ensure_ascii=False), encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = main(argv)
            return rc, buf.getvalue()

        CLEAN = "const w = 390.0;\nconst g = AppSpace.gapM;\n"
        rc, out = run(CLEAN)
        if rc != 0:
            print(f"self-test NG: 出どころのある値で落ちた（{rc}）\n   {out[:300]}")
            ok = False

        # **出どころの無い数値を1つ足すと落ちる**（これが本体）
        rc, out = run(CLEAN + "const stats = 138.0;\n")
        if rc != 1 or "138.0" not in out:
            print(f"self-test NG: 出どころの無い数値を通した（{rc}）"); ok = False
        if "Figma を直しても、ここは動きません" not in out:
            print("self-test NG: なぜ問題かを書いていない"); ok = False

        # 理由つきで宣言すれば通る
        rc, _ = run(CLEAN + "const anim = 1800;\n",
                    {"lib/ui/s.dart": {"1800": "動きの時間。Figma に動きの値は無い"}})
        if rc != 0:
            print(f"self-test NG: 理由つきの宣言があるのに落ちた（{rc}）"); ok = False
        rc, _ = run(CLEAN + "const anim = 1800;\n",
                    {"lib/ui/s.dart": {"1800": "  "}})
        if rc != 1:
            print(f"self-test NG: 理由が空の宣言を通した（{rc}）"); ok = False

        # `350.0` と `350` を同じものとして扱う
        rc, _ = run("const a = 390;\n")
        if rc != 0:
            print("self-test NG: 小数点の有無で別物にした"); ok = False

        # コメントの中の数値は見ない（**使っている値**だけを見る）
        rc, out = run(CLEAN + "// 82.4 は Figma の実測\n")
        if rc != 0:
            print(f"self-test NG: コメントの中の数値を咎めた（{rc}）"); ok = False

        # 生成物にないトークンは落ちる
        rc, out = run("const c = AppColor.noSuchColor;\n")
        if rc != 1 or "noSuchColor" not in out:
            print(f"self-test NG: 生成物に無いトークンを通した（{rc}）"); ok = False

        # 生成物（.g.dart）は見ない（出どころそのもの）
        (root / "lib" / "ui" / "x.g.dart").write_text("const z = 999.0;\n",
                                                      encoding="utf-8")
        rc, _ = run(CLEAN)
        if rc != 0:
            print("self-test NG: 生成物の中の数値を咎めた"); ok = False
        (root / "lib" / "ui" / "x.g.dart").unlink()

        # **出どころが読めなければ落ちる**（この道具自身の空振り）
        (root / "design" / "figma" / "frames.json").unlink()
        (root / "lib" / "theme" / "t.g.dart").unlink()
        rc, out = run(CLEAN)
        if rc != 2 or "全部まちがい" not in out:
            print(f"self-test NG: 出どころ0で報告を出した（{rc}）"); ok = False
    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
