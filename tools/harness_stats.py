#!/usr/bin/env python3
"""発火ログを集計して、ルールが効いているかを数で示す（任意の道具）。

design_check.py が書いた design/.harness_log.jsonl を読み、ルールごとに
「何か所に当たったか」「何か所を harness-ignore で除外したか」「編集中に何回当たったか」
「最後に当たったのはいつか」を出す。

**2026-08-29 に「仕組改善」の層としては廃止し、任意の道具として残しています**
（skills/mobile-harness-setup/SKILL.md）。ルールが増えすぎたときに引く道具です。

なぜ要るのか:
  ルールはレビュー指摘のたびに増える一方で、減らす仕組みが無い。増えるほど誤検出も
  増え、harness-ignore が乱発されるようになる。この集計があると
  「error に上げてよいルール」「もう要らないルール」「誤検出が多いルール」を
  印象ではなく数で判断できる。

## 2026-09-28 に直したこと

1. **説明どおりに呼ぶと落ちていました。** 案件のルートで
   `python3 design/harness/tools/harness_stats.py` を回すと、案件の `design/` にある
   入口のシム（`design/design_check.py`）を読み込み、そこに無い `load_rules()` を
   **引数なしで**呼んで `AttributeError` で止まっていました（エンジンの `load_rules` は
   規則ファイルのパスを受け取ります）。**エンジン本体をパスで読み込みます**
   （gap_report.py・seed_check.py と同じ形）。
2. **数え方がログの行数でした。** 全体走査（`--all`）は、走るたびに**残っている違反を
   全部**書き足します。行数で数えると「何回走査したか」を数えていることになります
   （PlantTalk・このマシンの実測: `no-legacy-pt-tokens` は 8,526 行、実際の箇所は 21、
   編集中に当たったのは 0 回）。1 か所が残ったまま 5 回走査されると、warn のルールが
   「error 昇格の候補」に見えていました。**箇所（ファイルと行の組）で数えます。**
3. 自己検査が無かったので、1 の壊れ方に誰も気づきませんでした。`--self-test` を足しました
   （それまでは「合否を出さない道具」として README の例外表に載っていました）。

使い方:
    python3 design/harness/tools/harness_stats.py
    python3 design/harness/tools/harness_stats.py --json
    python3 design/harness/tools/harness_stats.py --design <案件>/design   … 明示指定（path-check-ignore）
    python3 design/harness/tools/harness_stats.py --self-test

読み方:
  - 当たった箇所が多く、除外が 0 の warn … error に上げる候補
  - 除外の割合が高い … 誤検出か、ルールの範囲が広すぎる。見直しの候補
  - 観測期間中に一度も当たっていない … 棚卸しの候補（ただし後述の注意）

終了コード: 0 = 集計を出した / 2 = 出せなかった（design/ が無い・ログが無い・
ルールの一覧を読めない）。**合否は出しません**（候補を採るかは人が決めます）。

注意:
  - **このマシンの記録だけ**です。hook はマシンごとに登録するため、他のマシンや
    hook が動かない環境（python3 が無い等）の編集は含まれません
  - 箇所は「ファイルと行」の組です。行は編集で動くので、同じ違反が別の箇所として
    数えられることがあります（**多めに出る概算**）
  - 「一度も当たっていない」は観測期間が短いだけかもしれません。出力の観測期間を見て判断してください
  - ログはマシンごとに溜まるので .gitignore に入れてください
"""

import argparse
import importlib.util
import json
import os
import sys
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent / "engine" / "design_check.py"

#: 候補に挙げるのに要る箇所の数。**少なすぎる数では決めない**
MIN_SITES = 5


def load_engine(path=ENGINE):
    spec = importlib.util.spec_from_file_location("_engine", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def find_design(explicit=None, cwd=None):
    """集計する案件の design/。明示が無ければ cwd の design/（rules.json があるもの）。"""
    if explicit:
        return Path(explicit).resolve()
    d = Path(cwd or Path.cwd()) / "design"
    return d if (d / "rules.json").exists() else None


def rule_ids(design, engine_path=ENGINE):
    """全ルールの id と、読めなかったときの理由。

    ログには「当たった行」しか残らないので、一度も当たっていないルールを知るには
    ルールの一覧が要る。extends の解決を写すと二重管理になるので、エンジンの
    `load_rules` をそのまま使う。**案件の design/ にあるシムを読まない**
    （2026-09-28 まで、シムを読んで AttributeError で止まっていた）。

    戻り: (id の一覧 または None, 読めなかった理由)
    """
    if not engine_path.exists():
        return None, f"エンジンがありません: {engine_path}"
    try:
        engine = load_engine(engine_path)
        config = engine.load_rules(design / "rules.json")
    except Exception as e:  # noqa: BLE001  読めない理由をそのまま人に見せる
        return None, f"エンジンでルールを読めません（{type(e).__name__}: {e}）"
    if not config:
        return None, (f"ルールを読めません: {design / 'rules.json'}"
                      f"（無いか、JSON として壊れています）")
    return [r.get("id", "unknown") for r in config.get("rules", [])], ""


def aggregate(lines):
    """ログの行から、ルールごとの数を出す（純粋関数）。

    **箇所（ファイルと行の組）で数える。**行数で数えると、全体走査の回数を数えることになる。
    `edits` は編集中（hook）に当たった回数で、こちらは回数に意味がある（そのたびに止めている）。

    戻り: (ルール → 数, 時刻の一覧, ログの行数, うち全体走査の行数)
    """
    stats = defaultdict(lambda: {"sites": set(), "ignored": set(), "edits": 0,
                                 "last": "", "severity": "?"})
    stamps, n_lines, n_scan = [], 0, 0
    for line in lines:
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        n_lines += 1
        if r.get("source") == "scan":
            n_scan += 1
        s = stats[r.get("rule", "unknown")]
        s["severity"] = r.get("severity", "?")
        ts = r.get("ts", "")
        if ts:
            stamps.append(ts)
        site = (r.get("file", "?"), r.get("line"))
        if r.get("ignored"):
            s["ignored"].add(site)
            continue
        s["sites"].add(site)
        if r.get("source") == "hook":
            s["edits"] += 1
        if ts > s["last"]:
            s["last"] = ts
    return stats, sorted(stamps), n_lines, n_scan


def mark_of(s):
    """候補の印（純粋関数）。**候補を採るかは人が決める。**"""
    n, ig = len(s["sites"]), len(s["ignored"])
    if s["severity"] == "warn" and n >= MIN_SITES and ig == 0:
        return "→ error に上げる候補"
    if n + ig >= MIN_SITES and ig / (n + ig) >= 0.5:
        return "→ 除外が多い。見直しの候補"
    return ""


def span_of(stamps):
    if not stamps:
        return "不明"
    try:
        d0 = datetime.fromisoformat(stamps[0])
        d1 = datetime.fromisoformat(stamps[-1])
        return f"{stamps[0][:10]} 〜 {stamps[-1][:10]}（{(d1 - d0).days} 日）"
    except ValueError:
        return f"{stamps[0][:10]} 〜 {stamps[-1][:10]}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="発火ログを箇所で集計する（合否は出さない）")
    parser.add_argument("--design", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()

    design = find_design(args.design)
    if design is None:
        print("design/rules.json が見つかりません。案件のルートで実行するか、"
              "--design <案件>/design を渡してください", file=sys.stderr)
        return 2
    log = design / ".harness_log.jsonl"
    if not log.exists():
        print(f"発火ログがありません: {log}\n"
              f"  違反が一度も無いのか、このマシンで hook が動いていないのか、区別できません。"
              f"**0 件は『綺麗』ではなく『見ていない』です**", file=sys.stderr)
        return 2

    stats, stamps, n_lines, n_scan = aggregate(
        log.read_text(encoding="utf-8").splitlines())
    ids, why = rule_ids(design)
    silent = sorted(set(ids) - set(stats)) if ids is not None else None

    if args.json:
        print(json.dumps({
            "span": span_of(stamps), "lines": n_lines, "scanLines": n_scan,
            "rules": {k: {"severity": s["severity"], "sites": len(s["sites"]),
                          "ignoredSites": len(s["ignored"]), "edits": s["edits"],
                          "last": s["last"],
                          "inList": None if ids is None else k in ids,
                          "mark": "" if ids is not None and k not in ids else mark_of(s)}
                      for k, s in sorted(stats.items())},
            "silent": silent, "silentUnknownBecause": why or None,
        }, ensure_ascii=False, indent=1))
        if ids is None:
            return 2
        return 0

    print(f"観測期間: {span_of(stamps)}   ※このマシンの記録のみ")
    print(f"ログ {n_lines:,} 行（うち全体走査 {n_scan:,} 行）。"
          f"**行数ではなく箇所（ファイルと行の組）で数えています**")
    print(f"{'ルール':36} {'強さ':6} {'箇所':>5} {'除外':>5} {'編集中':>6}  最後に当たった日時")
    print("-" * 92)
    order = sorted(stats, key=lambda k: (-len(stats[k]["sites"]), k))
    for rid in order:
        s = stats[rid]
        # **いまの一覧に無いルールには候補の印を付けない。**削除・改名したルールを
        # 「error に上げる候補」と勧めていた（PlantTalk の実データで 3 本）
        gone = ids is not None and rid not in ids
        mark = "（いまの一覧に無い。削除か改名されたルール）" if gone else mark_of(s)
        print(f"{rid:36} {s['severity']:6} {len(s['sites']):>5} {len(s['ignored']):>5} "
              f"{s['edits']:>6}  {s['last'][:16] or '-'}  {mark}".rstrip())

    if ids is None:
        print(f"\n**一度も当たっていないルールは出していません**: {why}", file=sys.stderr)
        return 2
    if silent:
        print(f"\n観測期間中に一度も当たっていないルール（{len(silent)}件）:")
        for rid in silent:
            print(f"  - {rid}")
        print("  ※ 期間が短いだけの可能性があります。十分な期間を観測してから棚卸しを判断してください")
    else:
        print("\n全ルールが観測期間中に当たっています。")
    return 0


def self_test() -> int:
    """偽の案件を作って、**説明どおりの呼び方**で回す。"""
    ok = True

    def check(cond, msg):
        nonlocal ok
        if not cond:
            print(f"self-test NG: {msg}")
            ok = False

    def log_line(rule, sev, file, line, source="scan", ignored=False, ts="2026-09-01T00:00:00+00:00"):
        return json.dumps({"ts": ts, "rule": rule, "severity": sev, "file": file,
                           "line": line, "kind": "ignored" if ignored else "hit",
                           "ignored": ignored, "source": source})

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        design = root / "design"
        design.mkdir()
        rules = [{"id": i, "severity": sev, "pattern": "x", "forbidden": "-", "instead": "-"}
                 for i, sev in (("r-warn", "warn"), ("r-lingering", "warn"),
                                ("r-err", "error"), ("r-silent", "error"))]
        (design / "rules.json").write_text(json.dumps({"rules": rules}), encoding="utf-8")
        # **案件の入口のシムを置く。**2026-09-28 まで、これを読んで落ちていた（実害の形そのもの）
        (design / "design_check.py").write_text("# 案件の入口（load_rules を持たない）\n",
                                               encoding="utf-8")
        lines = []
        # r-warn: 6 か所に当たる（うち 4 回は編集中）。除外 0 → error に上げる候補
        for n in range(6):
            lines.append(log_line("r-warn", "warn", f"a{n}.swift", 3,
                                  source="hook" if n < 4 else "scan",
                                  ts=f"2026-09-0{n + 1}T00:00:00+00:00"))
        # r-lingering: **1 か所が残ったまま 10 回走査された。**行数で数えると候補に見える（直す前の誤り）
        lines += [log_line("r-lingering", "warn", "b.swift", 7) for _ in range(10)]
        # r-err: 2 か所に当たり、3 か所を除外 → 見直しの候補
        lines += [log_line("r-err", "error", f"c{n}.swift", 1) for n in range(2)]
        lines += [log_line("r-err", "error", f"d{n}.swift", 1, ignored=True) for n in range(3)]
        # r-gone: ログにはあるが、いまの一覧に無い
        lines.append(log_line("r-gone", "error", "e.swift", 1))
        # r-gone-warn: 一覧に無い warn が 5 か所。**無いルールを「上げる候補」と勧めない**
        lines += [log_line("r-gone-warn", "warn", f"g{n}.swift", 1) for n in range(5)]
        lines.append("{壊れた行")
        (design / ".harness_log.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

        def run(argv, cwd=None):
            import contextlib
            import io
            out, err = io.StringIO(), io.StringIO()
            here = os.getcwd()
            try:
                if cwd:
                    os.chdir(cwd)
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    rc = main(argv)
            finally:
                os.chdir(here)
            return rc, out.getvalue() + err.getvalue()

        # 1. **説明どおりの呼び方**（案件のルートで、--design を付けずに）
        rc, text = run([], cwd=root)
        check(rc == 0, f"案件のルートで回すと 0 で集計を出すはず（rc={rc}）: {text[:200]}")
        row = {ln.split()[0]: ln for ln in text.splitlines() if ln.startswith("r-")}
        check("error に上げる候補" in row.get("r-warn", ""), f"6 か所・除外 0 の warn を候補にしていない: {row.get('r-warn')}")
        check("候補" not in row.get("r-lingering", "-"),
              f"**1 か所を 10 回走査しただけの warn を候補にした**（行数で数えている）: {row.get('r-lingering')}")
        check("見直しの候補" in row.get("r-err", ""), f"除外 3/5 のルールを見直しの候補にしていない: {row.get('r-err')}")
        check("いまの一覧に無い" in row.get("r-gone", ""), f"一覧に無いルールを言っていない: {row.get('r-gone')}")
        check("候補" not in row.get("r-gone-warn", "候補") and "いまの一覧に無い" in row.get("r-gone-warn", ""),
              f"**いまの一覧に無いルールを候補として勧めた**: {row.get('r-gone-warn')}")
        check("r-silent" in text.split("一度も当たっていないルール")[-1],
              "一度も当たっていないルールを出していない")

        # 2. --json の数
        rc, text = run(["--design", str(design), "--json"])
        try:
            j = json.loads(text)
        except json.JSONDecodeError:
            j = {}
        r = j.get("rules", {})
        check(rc == 0, f"--json が 0 で返っていない（rc={rc}）")
        check(r.get("r-warn", {}).get("sites") == 6 and r.get("r-warn", {}).get("edits") == 4,
              f"r-warn の箇所・編集中の回数が違う: {r.get('r-warn')}")
        check(r.get("r-lingering", {}).get("sites") == 1, f"r-lingering を行数で数えた: {r.get('r-lingering')}")
        check(r.get("r-err", {}).get("ignoredSites") == 3, f"除外の箇所が違う: {r.get('r-err')}")
        check(j.get("silent") == ["r-silent"], f"一度も当たっていないルールが違う: {j.get('silent')}")
        check(r.get("r-gone-warn", {}).get("mark") == "" and r.get("r-gone-warn", {}).get("inList") is False,
              f"--json でも一覧に無いルールに印を付けた: {r.get('r-gone-warn')}")
        check(j.get("lines") == 27 and j.get("scanLines") == 23,
              f"ログの行数が違う（壊れた行は数えない）: {j.get('lines')} / {j.get('scanLines')}")

        # 3. design/ が見つからない → 2
        rc, text = run([], cwd=root / "design")
        check(rc == 2 and "見つかりません" in text, f"design/ が無いのに 2 で止まらない（rc={rc}）")

        # 4. ログが無い → 2（**0 件を『綺麗』と言わない**）
        (design / ".harness_log.jsonl").rename(design / "log.bak")
        rc, text = run(["--design", str(design)])
        check(rc == 2 and "区別できません" in text, f"ログが無いのに 2 で止まらない（rc={rc}）")
        (design / "log.bak").rename(design / ".harness_log.jsonl")

        # 5. ルールの一覧を読めない → 表は出すが 2（一度も当たっていないルールを出せない）
        (design / "rules.json").write_text("{壊れた", encoding="utf-8")
        rc, text = run(["--design", str(design)])
        check(rc == 2 and "一度も当たっていないルールは出していません" in text and "r-warn" in text,
              f"ルールを読めないのに 2 で止まらない（rc={rc}）")
        rc, text = run(["--design", str(design), "--json"])
        check(rc == 2, f"--json でもルールを読めなければ 2 のはず（rc={rc}）")
        ids, why = rule_ids(design, engine_path=root / "ない.py")
        check(ids is None and "エンジンがありません" in why, f"エンジンが無いのに一覧を返した: {why}")

    print("self-test: OK" if ok else "self-test: NG")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
