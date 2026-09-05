#!/usr/bin/env python3
"""変異試験。各道具の「落とす」経路を1つずつ潰して、自己検査が赤くなるかを見る（2026-09-05・#72）。

## なぜ要るか

2026-09-05 の実測: 38本の道具の `return 1` / `return 2`（違反を見つけたときの帰り道）185本を
1本ずつ `return 0` に書き換えて self-test を回したところ、**88本（47%）が素通りした。**
自己検査があっても、その経路を試していなければ「壊しても気づかない」。
**「落ちることを見てから採用する」を、記憶ではなく機械にする。**

計測の誤りも記録する: `return True` は Python では `1` と等しく、`return 1` の置換に
当たらないので素通りに見える（10本）。ここでは AST の定数が bool のものを除く。

## 使い方

    python3 attack/mutation_test.py            # 素通りが allow に無ければ落ちる
    python3 attack/mutation_test.py --list     # 全部の結果を出す

`attack/mutation-allow.json` に、**試験しにくい理由**つきで素通りを許す経路を書く
（git や GitHub の失敗など、環境の経路）。理由の無い素通りは落ちる。
"""

import ast
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOW = ROOT / "attack" / "mutation-allow.json"


def selftest_ok(f, cwd):
    try:
        r = subprocess.run([sys.executable, str(f), "--self-test"],
                           capture_output=True, text=True, timeout=240, cwd=cwd, errors="replace")
    except subprocess.TimeoutExpired:
        return None
    o = r.stdout + r.stderr
    return ("self-test: OK" in o) or ("件パス" in o and "NG" not in o)


def failure_returns(src):
    """self_test の外にある `return 1` / `return 2`（bool は除く）の行番号。"""
    tree = ast.parse(src)
    skip = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name.startswith("self_test"):
            skip |= set(range(n.lineno, (n.end_lineno or n.lineno) + 1))
    out = []
    for n in ast.walk(tree):
        if (isinstance(n, ast.Return) and isinstance(n.value, ast.Constant)
                and type(n.value.value) is int and n.value.value in (1, 2)
                and n.lineno not in skip):
            out.append(n.lineno)
    return sorted(set(out))


def main(argv=None):
    listing = "--list" in (argv or sys.argv[1:])
    allow = json.loads(ALLOW.read_text(encoding="utf-8")) if ALLOW.exists() else {}
    # `$patterns`: 帰り道の直前3行に当たる正規表現で、まとめて許す。
    # 「設定が無い・壊れている」の停止（return 2）は attack/broken_input_test.py が
    # 全道具に一律で当てているので、道具ごとの self-test に同じ試験を並べない
    import re as _re
    patterns = [(_re.compile(x["match"]), x["why"]) for x in allow.get("$patterns", [])]
    work = Path(tempfile.mkdtemp())
    try:
        for d in ("tools", "engine", "gate", "rules", "ci", "fingerprint", "exporters"):
            if (ROOT / d).exists():
                shutil.copytree(ROOT / d, work / d, ignore=shutil.ignore_patterns("__pycache__"))
        for f in ("README.md", "DESIGN.md"):
            if (ROOT / f).exists():
                shutil.copy(ROOT / f, work / f)
        survivors, measured, paths_total = [], 0, 0
        for f in sorted((work / "tools").glob("*.py")):
            src = f.read_text(encoding="utf-8")
            if '"--self-test"' not in src and "--selftest" not in src:
                continue
            targets = failure_returns(src)
            if not targets:
                continue
            if selftest_ok(f, work) is not True:
                continue                      # 基準で通らない道具は測れない（別の段が見る）
            measured += 1
            lines = src.splitlines(keepends=True)
            for ln in targets:
                paths_total += 1
                orig = lines[ln - 1]
                lines[ln - 1] = orig.replace("return 1", "return 0").replace("return 2", "return 0")
                f.write_text("".join(lines), encoding="utf-8")
                r = selftest_ok(f, work)
                lines[ln - 1] = orig
                if r is not False:
                    key = f"{f.name}:{ln}"
                    ctx = "".join(lines[max(0, ln - 7):ln])   # 長い案内文の帰り道も拾う
                    # **型で許すのは停止（return 2）だけ。** 違反（return 1）の帰り道は必ず
                    # その道具の self-test で見る。近くの案内文に当たって違反の経路まで
                    # 許してしまった（exporter_check:243 を一度隠した）
                    by_pattern = "return 2" in orig and any(rx.search(ctx) for rx, _ in patterns)
                    allowed = key in allow or by_pattern
                    survivors.append((key, orig.strip()[:70], allowed))
            f.write_text(src, encoding="utf-8")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    unlisted = [s for s in survivors if not s[2]]
    if listing:
        for key, code, allowed in survivors:
            print(f"  {'許可' if allowed else '**素通り**'} {key}  {code}")
    print(f"mutation_test: 道具 {measured} 本 / 落とす経路 {paths_total} 本 / 素通り {len(survivors)} 本"
          f"（理由つきで許可 {len(survivors) - len(unlisted)} / **理由なし {len(unlisted)}**）")
    if unlisted:
        print("理由の無い素通り（self-test がその経路を見ていない）:")
        for key, code, _ in unlisted:
            print(f"  {key}  {code}")
        print(f"  → その経路を通す self-test を足すか、試験しにくい理由を {ALLOW.name} に書く")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
