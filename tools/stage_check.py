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
- **落ちるケースが本物か**（`--min-coverage` は行数しか見ない。1行通れば
  数には入る）。中身が正しいかは人が見る
- 確かめた方法: --self-test（self-test の無い道具を段に足すと落ちること）

## 使い方（案件のルートで）

    python3 design/harness/tools/stage_check.py [--verify design/verify.sh]
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

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


def self_test_coverage(tool_path):
    """その道具の self-test が、本体を何行通るかを返す（2026-09-02 新設）。

    **`stage_check` はそれまで「self-test を持っているか」しか見ていなかった。**
    持っていても中身が薄ければ、何も見ていないのと同じ。実測で分かった例:

      fingerprint_parity   80行中  9行（11%）… 固定具の識別力だけを見ており、
                                              **main() を1行も通っていなかった**
      impl_coverage_check  36行中  7行（19%）… トークン照合の本体が0行
                                              （planttalk が 2026-09-02 に指摘）

    実行行は `ast` で数える（コメントと文字列だけの行を除くため）。
    戻りは (本体の行数, 通った行数) または None（self-test を持たない）。
    """
    import ast as _ast
    import importlib.util as _ilu
    import io as _io
    import contextlib as _ctx

    src = tool_path.read_text(encoding="utf-8")
    try:
        tree = _ast.parse(src)
    except SyntaxError:
        return None
    st = next((n for n in _ast.walk(tree)
               if isinstance(n, _ast.FunctionDef) and n.name == "self_test"), None)
    if st is None:
        return None
    st_lines = set(range(st.lineno, (st.end_lineno or st.lineno) + 1))
    body = {n.lineno for n in _ast.walk(tree)
            if isinstance(n, _ast.stmt) and n.lineno not in st_lines}
    if not body:
        return None

    spec = _ilu.spec_from_file_location(f"_cov_{tool_path.stem}", tool_path)
    mod = _ilu.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        return None

    hit = set()
    name = tool_path.name

    def tr(frame, ev, arg):
        if ev == "line" and frame.f_code.co_filename.endswith(name):
            hit.add(frame.f_lineno)
        return tr

    sys.settrace(tr)
    try:
        with _ctx.redirect_stdout(_io.StringIO()), _ctx.redirect_stderr(_io.StringIO()):
            mod.self_test()
    except SystemExit:
        pass
    except Exception:
        pass
    finally:
        sys.settrace(None)
    return len(body), len(body & hit)


def main(argv=None):
    ap = argparse.ArgumentParser(description="verify.sh の段が検査済みの道具か")
    ap.add_argument("--verify", type=Path, default=Path("design/verify.sh"))
    ap.add_argument("--tools", type=Path, default=HERE)
    ap.add_argument("--readme", type=Path, default=HERE.parent / "README.md")
    ap.add_argument("--run", action="store_true", default=True,
                    help="self-test を実際に走らせる（既定）")
    ap.add_argument("--no-run", dest="run", action="store_false")
    ap.add_argument("--min-coverage", type=int, metavar="N",
                    help="self-test が道具の本体の N%% 以上を通ることを求める。"
                         "省くと測って表示するだけ")
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

    lines = logical_lines(args.verify.read_text(encoding="utf-8"))
    seen_step = False
    for line in lines:
        m = STEP_RX.match(line)
        if m:
            seen_step = True
            label, cmd = m.group(1), m.group(2)
        else:
            # `step "..."` の形でない verify.sh もある（案件が手で書いた場合）。
            # **形式に依らず道具の呼び出しを拾う**（2026-08-29。それまで step 行
            # だけを見ており、形式の違う3案件を「0段・OK」と報告していた——
            # まさにこの道具が捕まえるはずの偽の緑だった）
            if not TOOL_RX.search(line):
                continue
            label, cmd = line.strip()[:60], line
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

    # 空振り検知: 中身があるのに1つも拾えていないなら、読み方が合っていない
    meaningful = [l for l in lines
                  if l.strip() and not l.strip().startswith("#")]
    if not checked and not foreign and len(meaningful) > 5:
        print(f"デザインハーネス異常: {args.verify} に {len(meaningful)} 行あるのに、"
              f"検査の段を1つも拾えませんでした。\n"
              f"  **『0段・問題なし』は『何も見ていない』という意味です。**\n"
              f"  ハーネスの道具を design/harness/tools/ 経由で呼ぶか、"
              f"雛形（ci/verify.sh.template）の step 形式に寄せてください。",
              file=sys.stderr)
        return 2

    print(f"段の健全性: 道具の段 {len(checked)}件が self-test 済み / "
          f"外部・例外の段 {len(foreign)}件")
    for f in foreign:
        print(f"  自己検査なし（外部の道具）: {f}")

    # **self-test の中身の薄さを測る**（2026-09-02 新設）。
    # それまで「持っているか」しか見ておらず、持っていても本体を1行も
    # 通らない道具があった（fingerprint_parity 11%・impl_coverage_check の
    # トークン照合は 0行）
    rows = []
    for tp in sorted(args.tools.glob("*.py")):
        r = self_test_coverage(tp)
        if r is None:
            continue
        body, hit = r
        rows.append((tp.stem, body, hit, hit * 100 // max(body, 1)))
    if rows:
        rows.sort(key=lambda x: x[3])
        thin = [r for r in rows if args.min_coverage and r[3] < args.min_coverage]
        print(f"\nself-test の網羅（道具 {len(rows)}本）: "
              f"最小 {rows[0][3]}% / 中央 {sorted(r[3] for r in rows)[len(rows)//2]}% / "
              f"最大 {rows[-1][3]}%")
        for name, body, hit, pct in rows[:5]:
            mark = "  ← **薄い**" if args.min_coverage and pct < args.min_coverage else ""
            print(f"  {name:<26} {hit:>3}/{body:<3}行 {pct:>3}%{mark}")
        if thin:
            problems.append(
                f"self-test が本体の {args.min_coverage}% を通らない道具が"
                f" {len(thin)} 本あります: "
                + " / ".join(f"{n}({p}%)" for n, _, _, p in thin)
                + "\n    **持っているだけでは何も証明していません。**"
                  "落ちるケースを足してください")

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

        # step 形式でない verify.sh でも道具を拾えること
        readme.write_text("（例外表なし）\n", encoding="utf-8")
        if run('#!/bin/sh\nset -e\n'
               'echo "検査します"\n'
               'python3 design/harness/tools/bad.py\n'
               'echo "おわり"\n') != 1:
            print("self-test NG: step 形式でない呼び出しを見逃した"); ok = False

        # 中身があるのに1つも拾えないなら落ちる（偽の緑を出さない）
        if run("#!/bin/sh\nset -e\n" + "".join(
                f'echo "何かする {i}"\n' for i in range(8))) != 2:
            print("self-test NG: 何も拾えないのに『問題なし』を出した"); ok = False
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
