#!/usr/bin/env python3
"""発火ログを集計して、ルールが効いているかを数で示す（仕組改善層）。

design_check.py が書いた design/.harness_log.jsonl を読み、ルールごとに
「何回発火したか」「何回 harness-ignore で除外されたか」「最後に発火したのはいつか」を出す。

なぜ要るのか:
  ルールはレビュー指摘のたびに増える一方で、減らす仕組みが無い。増えるほど誤検出も
  増え、harness-ignore が乱発されるようになる。この集計があると
  「error に上げてよいルール」「もう要らないルール」「誤検出が多いルール」を
  印象ではなく回数で判断できる。

使い方:
    python3 design/harness/tools/harness_stats.py
    python3 design/harness/tools/harness_stats.py --json

読み方:
  - 発火が多く ignored がゼロに近い warn … error に上げる候補
  - ignored の割合が高い … 誤検出が多い。パターンを絞るか、ルールを見直す候補
  - 観測期間中に一度も発火していない … 棚卸しの候補（ただし後述の注意）

注意:
  - **このマシンの記録だけ**です。hook はマシンごとに登録するため、他のマシンや
    hook が動かない環境（python3 が無い等）の編集は含まれません
  - 「発火ゼロ」は観測期間が短いだけかもしれません。出力の観測期間を見て判断してください
  - ログはマシンごとに溜まるので .gitignore に入れてください
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

# submodule から直接呼べる（コピー不要）。ログとルールは案件の design/ にある。
#   python3 design/harness/tools/harness_stats.py       … cwd の design/ を見る
#   python3 .../harness_stats.py --design <パス>        … 明示指定（path-check-ignore）
def _design_dir():
    import argparse as _a
    ap = _a.ArgumentParser(add_help=False)
    ap.add_argument("--design", type=Path, default=None)
    known, _rest = ap.parse_known_args()
    if known.design:
        return known.design.resolve()
    if (Path.cwd() / "design" / "rules.json").exists():
        return Path.cwd() / "design"
    return Path(__file__).resolve().parent


HERE = _design_dir()
LOG = HERE / ".harness_log.jsonl"


def all_rule_ids():
    """design_check.py の load_rules を再利用して全ルールidを列挙する。

    ログには「発火した行」しか残らないので、発火ゼロのルールを知るには
    ルール一覧が要る。合成（extends）の解決ロジックを写経すると二重管理に
    なるので、検査エンジン側の関数をそのまま使う。
    """
    sys.path.insert(0, str(HERE))
    try:
        import design_check
    except ImportError:
        return None
    config = design_check.load_rules()
    if not config:
        return None
    return [r.get("id", "unknown") for r in config.get("rules", [])]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--design", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if not LOG.exists():
        print("発火ログがまだありません（違反ゼロか、hook がこのマシンで未登録）。")
        return 0

    fired = defaultdict(int)
    ignored = defaultdict(int)
    last = {}
    severity = {}
    files = defaultdict(set)
    stamps = []

    for line in LOG.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        rid = r.get("rule", "unknown")
        stamps.append(r.get("ts", ""))
        severity[rid] = r.get("severity", "?")
        files[rid].add(r.get("file", "?"))
        if r.get("ignored"):
            ignored[rid] += 1
        else:
            fired[rid] += 1
            ts = r.get("ts", "")
            if ts > last.get(rid, ""):
                last[rid] = ts

    stamps = sorted(s for s in stamps if s)
    span = "不明"
    if stamps:
        try:
            d0 = datetime.fromisoformat(stamps[0])
            d1 = datetime.fromisoformat(stamps[-1])
            span = f"{stamps[0][:10]} 〜 {stamps[-1][:10]}（{(d1 - d0).days} 日）"
        except ValueError:
            span = f"{stamps[0][:10]} 〜 {stamps[-1][:10]}"

    known = all_rule_ids()
    silent = sorted(set(known) - set(fired) - set(ignored)) if known else None

    if args.json:
        print(json.dumps({
            "span": span, "fired": dict(fired), "ignored": dict(ignored),
            "last": last, "silent": silent,
        }, ensure_ascii=False, indent=1))
        return 0

    print(f"観測期間: {span}   ※このマシンの記録のみ")
    print(f"{'ルール':40} {'severity':9} {'発火':>5} {'除外':>5}  最終発火")
    print("-" * 86)
    for rid in sorted(set(fired) | set(ignored), key=lambda k: -fired.get(k, 0)):
        f, ig = fired.get(rid, 0), ignored.get(rid, 0)
        mark = ""
        if severity.get(rid) == "warn" and f >= 5 and ig == 0:
            mark = "  → error 昇格の候補"
        elif f + ig >= 5 and ig / max(1, f + ig) >= 0.5:
            mark = "  → 誤検出が多い。見直しの候補"
        print(f"{rid:40} {severity.get(rid,'?'):9} {f:>5} {ig:>5}  {last.get(rid,'-')[:16]}{mark}")

    if silent is None:
        print("\n（ルール一覧を読めなかったため、発火ゼロのルールは算出していません）")
    elif silent:
        print(f"\n観測期間中に一度も発火していないルール（{len(silent)}件）:")
        for rid in silent:
            print(f"  - {rid}")
        print("  ※ 期間が短いだけの可能性があります。十分な期間を観測してから棚卸しを判断してください")
    else:
        print("\n全ルールが観測期間中に発火しています。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
