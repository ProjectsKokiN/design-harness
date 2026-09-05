#!/usr/bin/env python3
"""溜めた指摘を早期 `return 0` で捨てている検査を見つける（2026-09-05 新設・#69）。

## 実害（aub-familywalk・2026-09-04〜05）

`machine_tasks_check.py` に「依頼 0 件を宣言して通す」を足したときの書き方が原因で、
**受信箱（MACHINE_TASKS.md）が 3 回 33 行まで削られ、2 回は verify.sh が緑だった。**

    if not secs:
        m = re.search(NASHI ...)
        if not m:
            return 2
        print('他マシンへの依頼: 0件')
        return 0        # ← それまでに溜めた ng を捨てていた

**「0 件は宣言で通す」を足すたびに同じ形が入る**（書き方の癖であって、その1本の不具合ではない）。

## 見るもの

関数の中で `ng.append(…)`（`errs` / `problems` … も）と**溜めている一覧**があり、その後に
**その一覧を見ていない `return 0`** がある形。次は正しい書き方なので咎めない:

    if not ng: return 0                 # 一覧を見てから帰る
    if ng: …; return 1                  # 先に落として、その下で return 0
    return 0 if not ng else 1           # 式の中で見ている

どうしても要る所は、その `return` の行に `# swallow-ok: 理由` を書く（理由の無い印は落とす）。

## 捕まえないもの

- 一覧の名前が一覧に無いもの（`out` / `result` など、戻り値として返す一覧は対象外）
- 一覧を見た **別の関数** に委ねている形（呼び出し先までは追わない）
- 確かめた方法: --self-test（捨てる形で落ち、3つの正しい形で落ちないこと）
"""

import argparse
import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

#: 「指摘を溜める一覧」として扱う名前。戻り値として返す一覧（out / result）は入れない
NAMES = {"ng", "errs", "errors", "problems", "issues", "bad", "fails", "failures",
         "warnings", "missing", "violations", "found_ng"}


def _names_in(node):
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _terminates(body):
    """ブロックの最後が return / raise / sys.exit なら真（落として帰る形）。"""
    if not body:
        return False
    last = body[-1]
    if isinstance(last, (ast.Return, ast.Raise)):
        return True
    if isinstance(last, ast.Expr) and isinstance(last.value, ast.Call):
        f = last.value.func
        return isinstance(f, ast.Attribute) and f.attr == "exit"
    return False


def _folds(body):
    """ブロックの中で別の一覧に畳み込んでいるか（`if missing: problems.append(…)`）。
    畳み込んだ先の一覧が見られるので、元の一覧は「見た」と数える。"""
    for n in ast.walk(ast.Module(body=list(body), type_ignores=[])):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr in ("append", "extend")
                and isinstance(n.func.value, ast.Name) and n.func.value.id in NAMES):
            return True
    return False


def check_source(src, lines, rel):
    """1ファイル分。戻り: [(行, 一覧の名前, 説明)]"""
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return [(e.lineno or 0, "-", f"構文が読めません: {e.msg}")]
    out = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        # 溜めている一覧: X.append / X.extend の最初の行
        acc = {}
        for n in ast.walk(fn):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr in ("append", "extend")
                    and isinstance(n.func.value, ast.Name) and n.func.value.id in NAMES):
                acc.setdefault(n.func.value.id, n.lineno)
        if not acc:
            continue

        def visit(block, guards, checked):
            """block を上から歩く。guards: 囲む if の test に出た名前。
            checked: この位置より上で「見て落とした」名前。"""
            checked = set(checked)
            for st in block:
                if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue                        # 内側の関数は別に見る
                if isinstance(st, ast.Return):
                    v = st.value
                    if isinstance(v, ast.Constant) and v.value == 0 and type(v.value) is int:
                        for name, first in acc.items():
                            if st.lineno <= first:
                                continue            # 溜め始める前の帰り道
                            if name in guards or name in checked:
                                continue
                            text = lines[st.lineno - 1] if st.lineno - 1 < len(lines) else ""
                            if "swallow-ok:" in text:
                                why = text.split("swallow-ok:", 1)[1].strip()
                                if why:
                                    continue
                                out.append((st.lineno, name, "swallow-ok に理由がありません"))
                                continue
                            out.append((st.lineno, name,
                                        f"`{name}` に溜めた指摘を見ないまま `return 0` しています"
                                        f"（{name} は {first} 行目から溜めている）。"
                                        f"**溜めたものを捨てると、その上の検査が全部消えます**"))
                    continue
                if isinstance(st, ast.If):
                    names = _names_in(st.test)
                    visit(st.body, guards | names, checked)
                    visit(st.orelse, guards | names, checked)
                    if names & set(acc) and (_terminates(st.body) or _folds(st.body)):
                        checked |= names & set(acc)  # ここから下は「見て落とした／畳んだ」あと
                    continue
                for field in ("body", "orelse", "finalbody"):
                    sub = getattr(st, field, None)
                    if isinstance(sub, list):
                        visit(sub, guards, checked)
                for h in getattr(st, "handlers", []) or []:
                    visit(h.body, guards, checked)
                for w in getattr(st, "cases", []) or []:      # match 文
                    visit(w.body, guards, checked)
        visit(fn.body, frozenset(), set())
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="溜めた指摘を早期 return で捨てていないか")
    ap.add_argument("--root", type=Path, nargs="*", default=[Path("tools"), Path("engine")],
                    help="歩く場所（既定: tools engine）")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()

    files = []
    for r in args.root:
        if r.is_file() and r.suffix == ".py":
            files.append(r)
        elif r.is_dir():
            files += sorted(p for p in r.rglob("*.py") if "__pycache__" not in p.parts)
    if not files:
        print(f"Python のファイルがありません: {[str(r) for r in args.root]}\n"
              f"  **0件は「綺麗」ではなく「見ていない」です。**", file=sys.stderr)
        return 2
    ng, fns = [], 0
    for f in files:
        src = f.read_text(encoding="utf-8", errors="ignore")
        fns += src.count("def ")
        for line, name, why in check_source(src, src.splitlines(), f):
            ng.append((f, line, name, why))
    if ng:
        print(f"溜めた指摘を捨てている帰り道があります（{len(ng)} 件 / {len(files)} ファイル）:",
              file=sys.stderr)
        for f, line, name, why in ng:
            print(f"  {f}:{line}  {why}", file=sys.stderr)
        return 1
    print(f"握りつぶし: 通った（{len(files)} ファイル / 関数 {fns} 本。一覧の名前 {len(NAMES)} 種を見た）")
    return 0


def self_test():
    ok = True

    def run(src):
        return check_source(src, src.splitlines(), Path("x.py"))

    BAD = ("def check(items):\n"
           "    ng = []\n"
           "    for i in items:\n"
           "        if i < 0:\n"
           "            ng.append(i)\n"
           "    if not items:\n"
           "        print('0件')\n"
           "        return 0\n"          # ← ng を見ていない（実害の形）
           "    if ng:\n"
           "        return 1\n"
           "    return 0\n")
    r = run(BAD)
    if len(r) != 1 or r[0][0] != 8 or r[0][1] != "ng":
        print(f"self-test NG: 捨てる形を見逃した／別の行を咎めた: {r}"); ok = False

    GOOD = ("def check(items):\n"
            "    errs = []\n"
            "    for i in items:\n"
            "        if i < 0:\n"
            "            errs.append(i)\n"
            "    if not errs:\n"
            "        return 0\n"                      # 見てから帰る
            "    return 1\n"
            "\n"
            "def check2(items):\n"
            "    errs = []\n"
            "    errs.append(1)\n"
            "    if errs:\n"
            "        print(errs)\n"
            "        return 1\n"
            "    print('OK')\n"
            "    return 0\n"                          # 上で落としている
            "\n"
            "def check3(items):\n"
            "    problems = []\n"
            "    problems.append(1)\n"
            "    return 0 if not problems else 1\n"   # 式の中で見ている
            "\n"
            "def check4(items):\n"
            "    ng = []\n"
            "    if not items:\n"
            "        return 0\n"                      # 溜め始める前の帰り道
            "    ng.append(1)\n"
            "    return 1 if ng else 0\n")
    r = run(GOOD)
    if r:
        print(f"self-test NG: 正しい形を咎めた: {r}"); ok = False

    # 印: 理由つきなら通り、理由が無ければ落ちる
    MARK = BAD.replace("        return 0\n    if ng:", "        return 0  # swallow-ok: 0件の宣言は別の道具が見る\n    if ng:")
    if run(MARK):
        print("self-test NG: 理由つきの印を通さない"); ok = False
    MARK2 = BAD.replace("        return 0\n    if ng:", "        return 0  # swallow-ok:\n    if ng:")
    r = run(MARK2)
    if len(r) != 1 or "理由" not in r[0][2]:
        print(f"self-test NG: 理由の無い印を通した: {r}"); ok = False

    # 畳み込み: missing を problems に移してから problems を見る形
    FOLD = ("def f(xs):\n    missing = []\n    problems = []\n    for x in xs:\n"
            "        missing.append(x)\n    if missing:\n        problems.append('a')\n"
            "    if problems:\n        return 1\n    return 0\n")
    if run(FOLD):
        print(f"self-test NG: 畳み込みの形を咎めた: {run(FOLD)}"); ok = False

    # 戻り値として返す一覧（out）は対象外
    OUT = "def f():\n    out = []\n    out.append(1)\n    if not True:\n        return 0\n    return out\n"
    if run(OUT):
        print("self-test NG: 戻り値の一覧を咎めた"); ok = False

    # else 側で見ている形（if ng: … else: return 0）
    ELSE = ("def f(x):\n    ng = []\n    ng.append(x)\n    if ng:\n        return 1\n"
            "    else:\n        return 0\n")
    if run(ELSE):
        print("self-test NG: else 側の帰り道を咎めた"); ok = False

    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
