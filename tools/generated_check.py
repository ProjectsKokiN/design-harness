#!/usr/bin/env python3
"""生成物に**機体固有の文字列**が入っていないかを見る（2026-09-06 新設・issue #78）。

## なぜ要るか

**決定論的な生成物は担当で縛りません**（2026-09-06 ユーザー確定・DESIGN.md
「生成物は担当で縛らない」）。誰が作り直しても同じになるからです。

**その前提が崩れると、共有が危険になります。** 生成物に機体固有の文字列が
入っていると、2台が交互に作り直して**上書きし合います**。しかも中身は同じなのに
`--check` は「生成し直していない」と嘘の理由で落ちます。

実害（2026-09-06 に3件・すべて実測）:

| 生成器 | 何が入っていたか |
|---|---|
| `gen_notcaptured.py` | `$読んだ器` にホーム入りの絶対パス **28 箇所**（`/Users/nishikawakoki/...`）。Mac mini（`/Users/k.nishikawa`）では**中身が同じでも必ず食い違い**、push できない行き止まりになった |
| `gen_gate.py` | `$生成元` が `str(p).replace(str(Path.home()), "~")`。**HOME の下に無いパスでは置換が起きず**、絶対パスがそのまま残った |
| （同上） | 上の結果、公開 CI では正本が見つからず「鮮度は見ていません」で **exit 0**。空振りの緑 |

## 何を見るか

    python3 tools/generated_check.py --root <案件>
    python3 tools/generated_check.py --self-test

対象は `generated.py` が**印から導いた生成物だけ**です（一覧は宣言しません）。

| 落とす | なぜ |
|---|---|
| ホームの下の絶対パス（`/Users/<誰か>/` `/home/<誰か>/` `C:\\Users\\<誰か>\\`） | 機体でホーム名が違う |
| 円記号の区切りを含むパス（`design\\figma\\x.json`） | Windows で `str(Path)` を書くと入る。Mac と食い違う |

**`~/...` は落としません。** ホームを `~` に畳んだ形は、どの機体でも同じ文字列になります
（これが正しい書き方）。

## 捕まえないもの

- 生成物が**べき等か**（同じ機体で2回生成して一致するか）。それは「生成物のべき等」の段
  （`gen_verify.py`）が見る。ここは**機体をまたいだときに一致するか**だけ
- 印を書き忘れた生成物。`generated.py` の判定に載らないものは見ない
- 確かめた方法: `--self-test`（4つの形それぞれが仕込みで落ちること・
  `~` 表記と相対パスで落ちないこと・違反時に exit 1 で落ちること）
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない
from generated import list_generated

#: ホームの下の絶対パス。**ホーム名は機体で違う**
HOME_ABS = re.compile(r"(/Users/[^/\"\s]+/|/home/[^/\"\s]+/|[A-Za-z]:\\\\?Users\\\\?)")

#: 円記号の区切りを含むパス。`str(Path)` を Windows で書くと入る
WIN_SEP = re.compile(r"[A-Za-z0-9_.\-]+\\{1,2}[A-Za-z0-9_.\-]+\\{1,2}[A-Za-z0-9_.\-]+")


def scan_text(text: str) -> list[str]:
    """機体固有の文字列を拾う。**行番号つきで返す。**"""
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        m = HOME_ABS.search(line)
        if m:
            out.append(f"行 {i}: ホームの下の絶対パス（{m.group(1)}…）")
            continue
        m = WIN_SEP.search(line)
        if m:
            out.append(f"行 {i}: 円記号の区切り（{m.group(0)}）")
    return out


def scan(root: Path, subdirs=None) -> tuple[list[str], int]:
    problems, n = [], 0
    for rel, _why in list_generated(root, subdirs):
        n += 1
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except OSError as e:
            problems.append(f"{rel}: 読めません（{e}）")
            continue
        for hit in scan_text(text):
            problems.append(f"{rel}  {hit}")
    return problems, n


def self_test() -> int:
    import tempfile
    ok = True
    CASES = [
        ("落とす: mac のホーム", '{"a": "/Users/nishikawakoki/dev/x.js"}', True),
        ("落とす: linux のホーム", '{"a": "/home/runner/work/x.js"}', True),
        ("落とす: Windows のホーム", '{"a": "C:\\\\Users\\\\koki\\\\x.js"}', True),
        ("落とす: 円記号の区切り", '{"a": "design\\\\figma\\\\x.json"}', True),
        ("落とさない: ~ に畳んだ形", '{"a": "~/dev/design-harness/x.js"}', False),
        ("落とさない: リポジトリ相対", '{"a": "design/figma/exporters/x.js"}', False),
        ("落とさない: /usr など個人でないパス", '{"a": "/usr/local/bin/node"}', False),
    ]
    for name, body, want in CASES:
        got = bool(scan_text(body))
        if got != want:
            print(f"self-test NG: {name} → 検出 {got}（期待 {want}）")
            ok = False

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "design" / "figma").mkdir(parents=True)
        gen = root / "design" / "figma" / "g.json"
        hand = root / "design" / "rules.json"
        # 手で書くものは見ない（印が無いので導出に載らない）
        hand.write_text('{"a": "/Users/dareka/x"}', encoding="utf-8")

        gen.write_text('{"$手で書き換えない": "gen", "a": "/Users/dareka/x"}',
                       encoding="utf-8")
        problems, n = scan(root)
        if n != 1:
            print(f"self-test NG: 生成物の数が違う（{n}・期待 1）"); ok = False
        if not problems:
            print("self-test NG: 生成物の機体固有の文字列を見逃した"); ok = False
        if any("rules.json" in p for p in problems):
            print("self-test NG: 手で書くものまで見ている"); ok = False

        # **違反したときに 1 で落ちるか**を main() ごと確かめる
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf), contextlib.redirect_stdout(buf):
            rc = main(["--root", str(root)])
        if rc != 1:
            print(f"self-test NG: 違反があるのに exit {rc}（期待 1）"); ok = False

        gen.write_text('{"$手で書き換えない": "gen", "a": "~/dev/x"}', encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = main(["--root", str(root)])
        if rc != 0:
            print(f"self-test NG: 違反が無いのに exit {rc}（期待 0）"); ok = False

    if ok:
        print("self-test: OK")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--subdir", action="append", metavar="DIR",
                    help="歩く場所（複数可。既定 design。`.` でリポジトリ全体）")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    problems, n = scan(args.root, args.subdir)
    if problems:
        print("生成物に機体固有の文字列が入っています。", file=sys.stderr)
        print("**このままだと共有できません**（2台が上書きし合い、"
              "中身が同じでも --check が嘘の理由で落ちます）。", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        print("\n  生成器を直してください。リポジトリ相対 + `as_posix()` が正しい形です\n"
              "  （2026-09-06 の gen_notcaptured.py・gen_gate.py が例）。", file=sys.stderr)
        return 1
    if n == 0:
        where = " / ".join(args.subdir or ["design"])
        print(f"生成物が1件も見つかりません（{args.root} の {where}）。\n"
              f"  **0件は「共有して安全」ではなく「見ていない」です。**\n"
              f"  歩く場所が違うか（`--subdir`）、生成器が印を書いていません"
              f"（2026-09-06 実測: design/ を持たないリポジトリで既定のまま回して"
              f"空振りの緑になっていました）。", file=sys.stderr)
        return 2
    print(f"生成物 {n} 件。機体固有の文字列はありません（共有して安全）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
