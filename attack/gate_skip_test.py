#!/usr/bin/env python3
"""CI の集計が「飛ばした関門」を緑にしないかを、実際に回して見る（#12）。

## なぜ要るか

`ci/app-verify.yml.template` の集計は**シェルで書かれていて、誰も試していなかった。**
flash-compose の実害（2026-09-03）:

| 条件 | 状態 | CI の出力 | CI の色 |
|---|---|---|---|
| 7（実装網羅） | 設定が無い | 「飛ばしました。**条件7 が誰も見ていません**」 | **緑** |
| 5（再現性の判定） | **段そのものが無い** | 何も出ない | **緑** |

`RAN -eq 0`（全部飛ばした）しか捕まえておらず、7段のうち2段が飛んでも緑だった。
`production-gate.md` は「条件は全部満たす」と書いているが、**確かめる機械が無かった。**

## 何をするか

テンプレートから印（`<<<集計ここから>>>` …）で囲んだシェルを抜き出し、
合成した段の呼び出しを挟んで回す。**印を消すとこの試験は落ちる。**
"""

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "ci" / "app-verify.yml.template"


def slice_between(text, start, end):
    m = re.search(re.escape(start) + r"(.*?)" + re.escape(end), text, re.S)
    if not m:
        raise SystemExit(
            f"印が見つかりません: {start} … {end}\n"
            f"  {TEMPLATE} の印を消さないでください"
            f"（消すと集計を誰も試さなくなります）。")
    return "\n".join(l[10:] if l.startswith(" " * 10) else l
                     for l in m.group(1).splitlines())


def run_case(stages, live=("1", "5", "7", "8", "9")):
    """合成した段を回して、集計の終了コードと出力を返す。"""
    text = TEMPLATE.read_text(encoding="utf-8")
    head = slice_between(text, "<<<集計ここから>>>", "<<<集計ここまで>>>")
    tail = slice_between(text, "<<<まとめここから>>>", "<<<まとめここまで>>>")
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        gate = d / "gate"
        gate.mkdir()
        (gate / "conditions.json").write_text(json.dumps(
            {"生きている条件": {c: {"見出し": f"条件{c}"} for c in live}},
            ensure_ascii=False), encoding="utf-8")
        script = "\n".join([
            "set -u", f'H="{d}/tools"', head, stages, tail, "exit $FAILED"])
        (d / "tools").mkdir()
        r = subprocess.run(["bash", "-c", script], capture_output=True,
                           text=True, cwd=d)
        return r.returncode, r.stdout + r.stderr


CASES = [
    ("関門の段を全部走らせたら通る",
     "\n".join(f'run "段（条件{c}）" - true' for c in ("1", "5", "7", "8", "9")),
     0, None),
    ("関門の段を skip_gate で飛ばしたら落ちる",
     "\n".join(f'run "段（条件{c}）" - true' for c in ("1", "5", "8", "9"))
     + '\nskip_gate "実装網羅（条件7）" "設定がありません"',
     1, "条件を測る段です"),
    ("関門の段そのものが無ければ落ちる（飛ばした記録すら残らない形）",
     "\n".join(f'run "段（条件{c}）" - true' for c in ("1", "7", "8", "9")),
     1, "条件5 を測った段がありません"),
    ("関門でない段は飛ばしても落ちない",
     "\n".join(f'run "段（条件{c}）" - true' for c in ("1", "5", "7", "8", "9"))
     + '\nskip "ページの範囲" "宣言がありません"',
     0, None),
    ("段を1つも走らせなければ落ちる",
     'skip "何か" "理由"',
     1, "何も見ていません"),
    # skip_gate 自身の FAILED=1 を isolate する。条件の番号を持たない段を
    # skip_gate で飛ばすと、条件の掃き出しでは捕まらない。**この1件が無いと
    # skip_gate から FAILED=1 を消しても試験が通ってしまう**（2026-09-04 実測）
    ("番号を持たない関門の段を飛ばしても落ちる（掃き出しでは捕まらない形）",
     "\n".join(f'run "段（条件{c}）" - true' for c in ("1", "5", "7", "8", "9"))
     + '\nskip_gate "見なかったもの" "gaps.json がありません"',
     1, "飛ばした = 誰も見ていません"),
    ("段が落ちたら落ちる",
     "\n".join(f'run "段（条件{c}）" - true' for c in ("1", "5", "7", "8", "9"))
     + '\nrun "落ちる段" - false',
     1, None),
]


def main():
    ok = True
    for name, stages, want, needle in CASES:
        rc, out = run_case(stages)
        if rc != want:
            print(f"NG: {name} → exit {rc}（期待 {want}）")
            print("   " + out.strip().replace("\n", "\n   ")[:600])
            ok = False
        elif needle and needle not in out:
            print(f"NG: {name} → 「{needle}」が出力にない")
            ok = False

    # 条件の一覧そのものが無ければ落ちる（何件かを確かめる手段が無い）
    text = TEMPLATE.read_text(encoding="utf-8")
    head = slice_between(text, "<<<集計ここから>>>", "<<<集計ここまで>>>")
    tail = slice_between(text, "<<<まとめここから>>>", "<<<まとめここまで>>>")
    with tempfile.TemporaryDirectory() as td:
        script = "\n".join(["set -u", f'H="{td}/tools"', head,
                            'run "段（条件1）" - true', tail, "exit $FAILED"])
        Path(td, "tools").mkdir()
        r = subprocess.run(["bash", "-c", script], capture_output=True,
                           text=True, cwd=td)
        if r.returncode != 1 or "条件の一覧がありません" not in r.stdout + r.stderr:
            print(f"NG: 条件の一覧が無いのに落ちなかった（exit {r.returncode}）")
            ok = False

    print(f"gate_skip_test: {'OK' if ok else 'NG'}（{len(CASES) + 1} 件）")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
