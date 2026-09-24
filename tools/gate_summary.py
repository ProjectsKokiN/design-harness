#!/usr/bin/env python3
"""**この結果が、Figma との照合として何を保証しているか**を条件ごとに言う（#135・2026-09-24）。

## なぜ要るか

planttalk（2026-09-19）で、`design_check.py` 違反 0・`swiftc -parse` 全通過・
`verify.sh` 終了コード 0 を「通った」と読んで完了とし、**実機では Figma と全く違う
画面が出ました。** 3 つとも Figma とは比べていません——禁止パターンを踏んでいないか、
構文が壊れていないか、落ちた段が宣言で覆われているか、を見ているだけです。

**緑の意味が出力のどこにも書かれていない**ので、読む側（AI も人も）が
「Figma と合っている」と取り違えます。実際に取り違えました。

## 何を出すか

関門の条件（1・4・5・7・8・9）ごとに、その条件を測る段の結果を 1 行で。

    条件7  実装網羅        違反を宣言で覆っている   ← **Figma と合っていません**
    条件4  鮮度            確かめられなかった（宣言あり）
    条件1  禁止パターン    測って合格

最後に「**保証していないもの**」を並べます。緑でも、そこは合っていません。

## これは関門ではありません

判定は変えません（終了コードは常に 0）。**言うだけ**です。
関門の判定は `not_yet_check.py` が持っています（#134 で中核の扱いを分けました）。

入力: `--gate-file` … `<段の名前>\\t<終了コード>` を 1 行ずつ（verify.sh の全段）
      `--config`    … design/stages.json（「まだ測れない」の宣言を読む）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

#: stage_check.py / not_yet_check.py と同じ見分け方
COND_RX = re.compile(r"条件(\d+)")
#: 条件の意味（gate/production-gate.md の表から。**ここが正ではない。**表を読み替えたら直す）
MEANING = {
    "1": "禁止パターン 0・静的解析 0・テスト全通過",
    "4": "鮮度 — 書き出しが Figma の現状と一致",
    "5": "再現性の判定に穴が無い",
    "7": "実装網羅 100% — Figma にあるものが全部実装されている",
    "8": "検査が生きている — ルールが実際に発火する",
    "9": "見本と相互作用 — 形と数が Figma と一致",
}
KEY = "まだ測れない"


def norm(s: str) -> str:
    return re.sub(r"[\s（）()・:：/／、。.*`\"'\-—]+", "", str(s or ""))


def read_gate(path: Path):
    rows = []
    for l in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "\t" not in l:
            continue
        name, rc = l.rsplit("\t", 1)
        try:
            rows.append((name.strip(), int(rc.strip())))
        except ValueError:
            continue
    return rows


def declared(conf_path: Path) -> set:
    try:
        d = json.loads(conf_path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return set()
    decl = d.get(KEY) or {}
    return {norm(k) for k in decl} if isinstance(decl, dict) else set()


def classify(rows, decl):
    """条件番号 → [(段, 状態)]。状態は 4 つ。"""
    out: dict[str, list] = {}
    for name, rc in rows:
        conds = COND_RX.findall(name)
        if not conds:
            continue
        has = norm(name) in decl
        if rc == 0:
            state = "測って合格"
        elif rc == 2:
            state = "確かめられなかった（宣言あり）" if has else "確かめられなかった（**宣言なし**）"
        else:
            state = "**違反を宣言で覆っている**" if has else "**確かめて違反**"
        for c in conds:
            out.setdefault(c, []).append((name, state))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gate-file", type=Path)
    ap.add_argument("--config", type=Path, default=Path("design/stages.json"))
    ap.add_argument("--self-test", "--selftest", dest="self_test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if not a.gate_file or not a.gate_file.is_file():
        print("段の結果の控えがありません。**何を保証したか言えません。**")
        return 0
    rows = read_gate(a.gate_file)
    if not rows:
        print("段の結果が 1 件もありません。**何を保証したか言えません。**")
        return 0
    by = classify(rows, declared(a.config))
    if not by:
        print("**関門の条件（条件N）を名前に持つ段が 1 つもありません。**"
              "Figma との照合は、この結果からは何も言えません")
        return 0
    not_ok = []
    for c in sorted(by, key=int):
        for name, state in by[c]:
            short = COND_RX.sub("", name).replace("（:", "（").replace("（ ", "（")
            short = re.sub(r"（[^）]*）", "", short).strip() or name
            print(f"  条件{c}  {short:<18} {state}")
            if state != "測って合格":
                not_ok.append((c, state))
    print()
    if not not_ok:
        print("  **Figma との照合: 関門の条件はすべて測って合格しています。**")
        return 0
    print("  **この結果が保証していないもの:**")
    seen = set()
    for c, state in not_ok:
        if c in seen:
            continue
        seen.add(c)
        print(f"    条件{c}（{MEANING.get(c, '?')}）— {state}")
    if any("違反" in st for _, st in not_ok):
        print("  **「違反を宣言で覆っている」は、Figma と合っていないことが分かっている状態です。**"
              "宣言は免除であって、一致ではありません")
    return 0


def self_test() -> int:
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as td:
        r = Path(td)
        gate = r / "g.txt"
        conf = r / "stages.json"
        core = "実装網羅（条件7: Figma にあるものは全部実装）"
        conf.write_text(json.dumps({KEY: {core: {"why": "x", "reviewBy": "2099-01-01"}}},
                                   ensure_ascii=False), encoding="utf-8")

        def run(lines):
            import io, contextlib
            gate.write_text("\n".join(lines) + "\n", encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(["--gate-file", str(gate), "--config", str(conf)])
            return rc, buf.getvalue()

        rc, out = run([core + "\t1"])
        if "違反を宣言で覆っている" not in out:
            print("self-test NG: **違反を宣言で覆っているのに、そう言いません**"); ok = False
        if "保証していないもの" not in out:
            print("self-test NG: 保証していないものを出しません"); ok = False
        rc, out = run([core + "\t2"])
        if "確かめられなかった（宣言あり）" not in out:
            print("self-test NG: 確かめられなかった＋宣言あり、を区別できません"); ok = False
        rc, out = run(["鮮度（条件4: Figma 本体）\t2"])
        if "宣言なし" not in out:
            print("self-test NG: 宣言なしの 2 を区別できません"); ok = False
        rc, out = run([core + "\t0", "禁止パターン（全量・条件1）\t0"])
        if "すべて測って合格" not in out:
            print("self-test NG: 全部 0 なのに合格と言いません"); ok = False
        rc, out = run(["名前の照合（引いている名前）\t0"])
        if "1 つもありません" not in out:
            print("self-test NG: **中核の段が無いのに、何か保証したように見せています**"); ok = False
        if rc != 0:
            print("self-test NG: 判定を変えています（終了コードが 0 でない）"); ok = False
    print("self-test: " + ("OK" if ok else "NG"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
