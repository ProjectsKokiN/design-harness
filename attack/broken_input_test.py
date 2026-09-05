#!/usr/bin/env python3
"""設定が無い・壊れているときに、全道具が止まるかを一律に見る（2026-09-05・変異試験より）。

## なぜ要るか

変異試験（各道具の `return 2` を `return 0` に書き換えて self-test を回す）で、
**「入力が壊れているときに止まる」経路 63 本のうち、自己検査が見ているものが
1本も無かった。** 全部が素通りした。

これはハーネスの中心の主張——**「0件は『綺麗』ではなく『見ていない』」**——を
守っている経路そのもの。壊れた設定のまま `return 0` になれば、
「何も見ていないのに緑」が起きる。**一番守りたい場所が、一番試されていなかった。**

道具ごとに self-test を足すと 63 か所に同じ試験が並ぶ。ここで**一律に**見る。

## 見るもの

`--config` を持つ全道具に、(a) 存在しないパス、(b) `{broken` を渡し、
**exit 2 で止まること**（argparse の usage ではなく、道具自身の文言で）を確かめる。
"""

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"


def probe(tool, arg, cwd):
    try:
        r = subprocess.run([sys.executable, str(tool), "--config", arg],
                           capture_output=True, text=True, timeout=90, cwd=cwd)
    except subprocess.TimeoutExpired:
        return "timeout", ""
    err = r.stderr + r.stdout
    if err.lstrip().startswith("usage:"):
        return "usage", err
    return f"exit{r.returncode}", err


def main():
    ok = True
    tools = [f for f in sorted(TOOLS.glob("*.py"))
             if 'add_argument("--config"' in f.read_text(encoding="utf-8")]
    if len(tools) < 10:
        print(f"NG: --config を持つ道具が {len(tools)} 本しか見つからない（走査が空振り）")
        return 1
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "broken.json"
        bad.write_text("{broken", encoding="utf-8")
        for f in tools:
            for label, arg in (("無いパス", str(Path(td) / "nope.json")),
                               ("壊れた JSON", str(bad))):
                kind, err = probe(f, arg, td)
                if kind == "exit2":
                    continue
                ok = False
                why = {"exit0": "**通した**（何も見ていないのに緑）",
                       "usage": "argparse の usage で終わった（設定を読みに行っていない）",
                       "timeout": "止まらない"}.get(kind, f"終了コード {kind}")
                print(f"NG: {f.name} に{label}を渡すと {why}")
    print(f"broken_input_test: {'OK' if ok else 'NG'}（道具 {len(tools)} 本 × 2）")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
