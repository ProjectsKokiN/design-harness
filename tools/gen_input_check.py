#!/usr/bin/env python3
"""生成器の入力が Figma の機械書き出しだけかを見る（記録層の廃止・2026-08-29）。

aub-familywalk の実害: `gen_chrome_specs.py` が **AI の手書き記録**
（design/values/chrome.json）を読んで `chrome_specs.g.dart` を吐いていた。
誤った手書きの値が「自動生成。手で編集しない。」というヘッダを付けて出てくるので、
下流からは機械生成の値と見分けが付かない（**誤りの洗浄**）。
実測では、手書きの層から8件の値の誤りが出たのに対し、書き出しから
機械生成した層は0件だった。

## この検査が捕まえるもの

- `design/gen/*.py` の中の文字列リテラルに、`design/values` /（figma/ 配下でない）
  `.json` の読み取りが現れること
- テスト・実装が `design/values` を読んでいること（照合相手は書き出しだけ、の移行検査）

## この検査が捕まえないもの

- 動的に組み立てたパス（変数連結）。文字列リテラルしか見ない
- 生成器のロジックの誤り（べき等性は design/gen/verify.py の領域）
- 確かめた方法: --self-test（values を読む生成器を仕込んで落ちること）

## 使い方（案件のルートで）

    python3 design/harness/tools/gen_input_check.py \\
        [--gen design/gen] [--tests test] [--allow figma/ design/figma/]
"""

import argparse
import re
import sys
from pathlib import Path

#: 読み取りの気配。open(...) / read_text / json.load(open(...)) / Path(...)
READ_RX = re.compile(
    r"""(?:open|read_text|Path|load|loads)\s*\(?[^)\n]*?['"]([\w./-]+\.(?:json|md|csv|yaml|yml))['"]""")

#: 手書きの記録層。ここを読む生成器・テストは誤りの洗浄になる
BANNED = ("design/values", "values/")


def reads_in(path):
    out = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return out
    for i, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith("#") or "gen-input-ignore" in line:
            continue
        for m in READ_RX.finditer(line):
            out.append((i, m.group(1)))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="生成器・テストの入力が書き出しだけか")
    ap.add_argument("--gen", type=Path, default=Path("design/gen"))
    ap.add_argument("--tests", type=Path, default=Path("test"))
    ap.add_argument("--allow", nargs="*",
                    default=["figma/", "design/figma/", "gen/", "design/gen/"],
                    help="生成器が読んでよいパスの接頭辞（書き出しと生成器自身の中間物）")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    problems = []

    # 1) 生成器: 許可された接頭辞以外の読み取りを全部拾う（許可リスト方式）
    if args.gen.exists():
        for f in sorted(args.gen.glob("*.py")):
            for lineno, p in reads_in(f):
                name = p.split("/")[-1]
                ok = (any(p.startswith(a) or f"/{a}" in p for a in args.allow)
                      or "/" not in p)   # 素のファイル名は gen 内の中間物とみなす
                if any(b in p for b in BANNED):
                    problems.append(f"  {f}:{lineno}: 手書きの記録層を読んでいます: {p}")
                elif not ok:
                    problems.append(f"  {f}:{lineno}: 書き出し以外を入力にしています: {p}"
                                    f"（許可: {args.allow}）")

    # 2) テスト・実装: 記録層の参照が残っていないか（移行検査）
    for base in (args.tests, Path("lib")):
        if not base.exists():
            continue
        for f in sorted(base.rglob("*")):
            if f.suffix not in (".dart", ".py", ".ts", ".tsx", ".js", ".mjs"):
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if "gen-input-ignore" in line:
                    continue
                if any(b in line for b in BANNED) and (
                        ".json" in line or "values" in line.lower()):
                    if "design/values" in line:
                        problems.append(
                            f"  {f}:{i}: 記録層（design/values）を照合相手にしています。"
                            f"照合相手は figma/ の書き出しだけです")

    if problems:
        print("生成器・照合の入力に、手で書いた層が混ざっています"
              "（2026-08-29 記録層の廃止）:", file=sys.stderr)
        print("\n".join(sorted(set(problems))), file=sys.stderr)
        return 1
    print("OK: 生成器と照合の入力は Figma の書き出しだけです。")
    return 0


def self_test():
    import tempfile, os
    ok = True
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        gen = root / "design/gen"
        gen.mkdir(parents=True)
        (root / "test").mkdir()
        cwd = os.getcwd()
        os.chdir(root)
        try:
            (gen / "gen_good.py").write_text(
                'DOC = json.load(open("design/figma/components.json"))\n',
                encoding="utf-8")
            if main([]) != 0:
                print("self-test NG: 書き出しだけなのに落ちた"); ok = False

            (gen / "gen_bad.py").write_text(
                'DOC = json.load(open("design/values/chrome.json"))\n',
                encoding="utf-8")
            if main([]) != 1:
                print("self-test NG: 記録層を読む生成器で落ちなかった"); ok = False
            (gen / "gen_bad.py").unlink()

            (root / "test/t.dart").write_text(
                "final doc = File('design/values/header.json');\n",
                encoding="utf-8")
            if main([]) != 1:
                print("self-test NG: 記録層を読むテストで落ちなかった"); ok = False
            (root / "test/t.dart").write_text(
                "final doc = File('design/figma/frames.json');\n", encoding="utf-8")
            if main([]) != 0:
                print("self-test NG: 書き出しを読むテストなのに落ちた"); ok = False
        finally:
            os.chdir(cwd)
    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
