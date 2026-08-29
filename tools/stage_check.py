#!/usr/bin/env python3
"""verify.sh の各段が「落ちるところを見た」道具かを見る（aub 提案10・2026-08-29）。

## 実害

> 何も見ていない検査が緑で並ぶ。**この日だけで2回踏んだ**（aub-familywalk）

「落ちることを見てから採用する」は文章の決まりとして書いてあったが、
文章では守れなかった。**手順ではなく検査にする。**

## 見るもの

`verify.sh` の `step "..." ...` の各行について:

1. design-harness の道具を呼んでいるなら、その道具に `--self-test` があるか
2. あるなら、**実際に走らせて通るか**
3. 無いなら、`README.md` の例外表に理由つきで載っているか

## 捕まえないもの

- 案件固有のコマンド（`flutter test` / `npx tsc` など）。外部の道具なので
  self-test の有無を問わない。**ただし一覧には出す**（何が無検査かを見えるように）
- self-test の中身が薄いこと。落ちるケースを持っているかは人が見る
- 確かめた方法: --self-test（self-test の無い道具を段に足すと落ちること）

## 使い方（案件のルートで）

    python3 design/harness/tools/stage_check.py [--verify design/verify.sh]
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STEP_RX = re.compile(r'^\s*step\s+"([^"]+)"\s+(.*)$')
TOOL_RX = re.compile(r'(?:\$HARNESS|harness)/tools/([a-z_]+)\.py')
#: README の例外表から拾う道具名
EXC_RX = re.compile(r"^\|\s*`?([a-z_]+)`?[^|]*\|")


def logical_lines(text):
    """行継続（末尾の `\\`）をつないで1行にする。

    **2026-08-29 に自分で踏んだ**: verify.sh.template は
    `step "..." \\` で改行しており、継続を読まないと道具のパスが次の行に残る。
    その結果この道具は**全部の段を「外部の道具」と分類して緑を返した**——
    まさにこの道具が捕まえるはずの「何も見ていない検査」そのものだった。
    """
    out, buf = [], ""
    for line in text.splitlines():
        if line.rstrip().endswith("\\"):
            buf += line.rstrip()[:-1] + " "
            continue
        out.append(buf + line)
        buf = ""
    if buf:
        out.append(buf)
    return out


def documented_exceptions(readme):
    """README の「self-test を持たない道具」表に載っている道具名。"""
    if not readme.exists():
        return set()
    text = readme.read_text(encoding="utf-8")
    m = re.search(r"##\s*self-test を持たない道具.*?(?=\n##\s|\Z)", text, re.S)
    if not m:
        return set()
    out = set()
    for line in m.group(0).splitlines():
        mm = EXC_RX.match(line)
        if mm and mm.group(1) not in ("道具", "理由"):
            for name in re.findall(r"`([a-z_]+)`", line):
                out.add(name)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="verify.sh の段が検査済みの道具か")
    ap.add_argument("--verify", type=Path, default=Path("design/verify.sh"))
    ap.add_argument("--tools", type=Path, default=HERE)
    ap.add_argument("--readme", type=Path, default=HERE.parent / "README.md")
    ap.add_argument("--run", action="store_true", default=True,
                    help="self-test を実際に走らせる（既定）")
    ap.add_argument("--no-run", dest="run", action="store_false")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    if not args.verify.exists():
        print(f"verify.sh がありません: {args.verify}\n"
              f"  統合検査の入口が無い状態です（関門は CI と pre-push）。",
              file=sys.stderr)
        return 1

    exceptions = documented_exceptions(args.readme)
    problems, foreign, checked = [], [], []

    for line in logical_lines(args.verify.read_text(encoding="utf-8")):
        m = STEP_RX.match(line)
        if not m:
            continue
        label, cmd = m.group(1), m.group(2)
        tools = TOOL_RX.findall(cmd)
        if not tools:
            foreign.append(label)
            continue
        for name in tools:
            path = args.tools / f"{name}.py"
            if not path.exists():
                problems.append(f"「{label}」が呼ぶ {name}.py がありません")
                continue
            src = path.read_text(encoding="utf-8", errors="ignore")
            if "self_test" not in src:
                if name in exceptions:
                    foreign.append(f"{label}（{name}: 例外として明記済み）")
                else:
                    problems.append(
                        f"「{label}」が呼ぶ {name}.py に self-test がありません。\n"
                        f"      **落ちるところを見ていない検査を段に置かない。**\n"
                        f"      落ちるケースを足すか、README の例外表に理由を書いてください")
                continue
            if not args.run:
                checked.append(name)
                continue
            r = subprocess.run([sys.executable, str(path), "--self-test"],
                               capture_output=True, text=True, timeout=180)
            if r.returncode != 0:
                problems.append(f"「{label}」の {name}.py の self-test が落ちました:\n"
                                f"      {r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr.strip()[:150]}")
            else:
                checked.append(name)

    print(f"段の健全性: 道具の段 {len(checked)}件が self-test 済み / "
          f"外部・例外の段 {len(foreign)}件")
    for f in foreign:
        print(f"  自己検査なし（外部の道具）: {f}")
    if problems:
        print("\n落ちるところを見ていない段があります:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    return 0


def self_test():
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        tools = base / "tools"; tools.mkdir()
        (tools / "good.py").write_text(
            "import sys\ndef self_test():\n    print('self-test: OK')\n    return 0\n"
            "if __name__ == '__main__':\n    sys.exit(self_test())\n", encoding="utf-8")
        (tools / "bad.py").write_text("print('検査したふり')\n", encoding="utf-8")
        (tools / "failing.py").write_text(
            "import sys\ndef self_test():\n    return 1\n"
            "if __name__ == '__main__':\n    sys.exit(self_test())\n", encoding="utf-8")
        readme = base / "README.md"
        readme.write_text("## self-test を持たない道具（意図的な例外）\n\n"
                          "| 道具 | 理由 |\n|---|---|\n| `bad` | 外部に依存する |\n",
                          encoding="utf-8")
        v = base / "verify.sh"

        def run(body):
            v.write_text(body, encoding="utf-8")
            return main(["--verify", str(v), "--tools", str(tools),
                         "--readme", str(readme)])

        if run('step "よい段" "$PY" "$HARNESS/tools/good.py"\n') != 0:
            print("self-test NG: self-test のある道具で落ちた"); ok = False
        if run('step "落ちる段" "$PY" "$HARNESS/tools/failing.py"\n') != 1:
            print("self-test NG: self-test が落ちる道具を通した"); ok = False
        if run('step "例外の段" "$PY" "$HARNESS/tools/bad.py"\n') != 0:
            print("self-test NG: README に明記した例外で落ちた"); ok = False
        readme.write_text("（例外表なし）\n", encoding="utf-8")
        if run('step "無検査の段" "$PY" "$HARNESS/tools/bad.py"\n') != 1:
            print("self-test NG: self-test の無い道具を黙って通した"); ok = False
        if run('step "外部の段" flutter test\n') != 0:
            print("self-test NG: 外部コマンドの段で落ちた"); ok = False
        if run('step "存在しない段" "$PY" "$HARNESS/tools/nope.py"\n') != 1:
            print("self-test NG: 存在しない道具を通した"); ok = False

        # 行継続（\\ で改行）を読めること。読めないと道具を「外部」と誤分類し、
        # **全段を素通りさせて緑を返す**（2026-08-29 に自分で踏んだ）
        readme.write_text("（例外表なし）\n", encoding="utf-8")
        if run('step "継続の段" \\\n  "$PY" "$HARNESS/tools/bad.py"\n') != 1:
            print("self-test NG: 行継続を読めず、無検査の道具を通した"); ok = False
        if run('step "継続でよい段" \\\n  "$PY" "$HARNESS/tools/good.py"\n') != 0:
            print("self-test NG: 行継続でよい道具を落とした"); ok = False

    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
