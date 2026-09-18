#!/usr/bin/env python3
"""rules.json のルールが**本当に当たるか**を、同梱の仕込みで確かめる。

design-harness #124（2026-09-18）。ルールは正規表現なので、書いた時点では
「当たらないルール」と「違反が無いコード」が見分けられません。
**0件は「綺麗」ではなく「見ていない」かもしれない**ので、
各ルールに bad（必ず当たる）と good（当たってはいけない）を持たせて当てます。

終了コード:
  0 … 全部のルールで、bad が当たり good が当たらなかった
  1 … 当たらない bad か、当たってしまう good があった
  2 … 確かめられなかった（仕込みが無い・{{ }} が残っている・ファイルが読めない）

**2 を 0 と混ぜないこと。** 「仕込みが無いルール」を通すと、
配ったあとに「違反0件」と出ても、それが見ていないだけなのか分かりません。
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

PLACEHOLDER = re.compile(r"\{\{.*?\}\}", re.S)


def check_rule(rule: dict) -> tuple[str, list[str]]:
    """1件のルールを確かめ、('ok'|'ng'|'unknown', 理由の行) を返す。"""
    rid = rule.get("id", "(id 無し)")
    st = rule.get("_selftest")

    if st is None:
        return "unknown", [f"{rid}: 仕込みがありません（_selftest が無い）"]
    if "_skip" in st:
        # **「当てられない」は、宣言すれば通す。ただし `外した` の宣言と同じ形を要る。**
        # なぜ＝当てられない理由、かわりに＝では何で見るか。
        # **理由だけでは足りない**（stage_check の `外した` と同じ規律・2026-09-18）。
        sk = st["_skip"]
        if isinstance(sk, dict):
            why, alt = str(sk.get("なぜ", "")).strip(), str(sk.get("かわりに", "")).strip()
            if why and alt:
                return "declared", [f"{rid}: 当てられないと宣言 — {why} / かわりに: {alt}"]
            return "unknown", [
                f"{rid}: _skip に「なぜ」と「かわりに」の両方が要ります"
                f"（いまは なぜ={why!r} かわりに={alt!r}）"]
        return "unknown", [
            f"{rid}: _skip は「なぜ」と「かわりに」を持つ形で書いてください"
            f"（いまは文字列: {str(sk)[:40]!r}）"]

    pat = rule.get("pattern") or rule.get("trigger")
    if not pat:
        return "unknown", [f"{rid}: pattern も trigger もありません"]
    if PLACEHOLDER.search(pat):
        return "unknown", [f"{rid}: pattern に {{{{ }}}} が残っているので当てられません"]

    try:
        rx = re.compile(pat, re.S if rule.get("multiline") else 0)
    except re.error as e:
        return "ng", [f"{rid}: 正規表現が壊れています — {e}"]

    bad = st.get("bad") or []
    good = st.get("good") or []
    if not bad:
        return "unknown", [f"{rid}: bad（必ず当たる例）がありません"]

    msgs = []
    for s in bad:
        if not rx.search(s):
            msgs.append(f"{rid}: **当たるはずの仕込みに当たりませんでした** → {s!r}")
    for s in good:
        if rx.search(s):
            msgs.append(f"{rid}: **当たってはいけない例に当たりました** → {s!r}")
    return ("ng", msgs) if msgs else ("ok", [])


def chain(path: Path, seen: set[Path] | None = None) -> list[Path]:
    """`extends` を辿って、実際に当たるルールが載っている全ファイルを返す。

    **辿らないと、レジストリ側のルールが見られません。**
    FlashEnglish は自分のファイルに1件しか持たず、残り10件は参照先にあります
    （2026-09-18 実測）。ここを見ないと「1件確かめた」で通ってしまいます。
    """
    seen = seen if seen is not None else set()
    path = path.resolve()
    if path in seen or not path.is_file():
        return []
    seen.add(path)
    out = [path]
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return out  # mutation-ok: 読めない先は run() 側が 2 で報せる
    for rel in data.get("extends") or []:
        if isinstance(rel, str):
            out += chain(path.parent / rel, seen)
    return out


def run(path: Path) -> int:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:
        print(f"読めません: {path} — {e}")
        return 2

    rules = data.get("rules")
    if not isinstance(rules, list) or not rules:
        print(f"rules がありません: {path}")
        return 2

    ok = ng = unknown = declared = 0
    lines = []
    for r in rules:
        if not isinstance(r, dict) or "id" not in r:
            continue  # _note だけの要素
        verdict, msgs = check_rule(r)
        lines += msgs
        if verdict == "ok":
            ok += 1
        elif verdict == "ng":
            ng += 1
        elif verdict == "declared":
            declared += 1
        else:
            unknown += 1

    for l in lines:
        print(l)

    # **最後の1行に結果を出す。** stage_check は最終行だけを見る
    tail = (f"{path.name}: 当たった {ok} / 当たらない {ng} / "
            f"宣言して外した {declared} / 確かめられない {unknown}")
    if ng:
        print(f"NG: {tail}。**仕込みが効いていないルールは配らないこと。**")
        return 1
    if unknown:
        print(f"確かめられません: {tail}。_selftest を足すか、案件で {{{{ }}}} を具体化すること")
        return 2
    print(f"OK: {tail}")
    return 0


def self_test() -> int:
    """**この道具自身が空振りしていないか。** 壊れたルールを食わせて落ちるか見る。"""
    cases = [
        ("当たらない bad を見つける",
         {"id": "t1", "pattern": "AAA", "_selftest": {"bad": ["BBB"]}}, "ng"),
        ("当たる good を見つける",
         {"id": "t2", "pattern": "AAA", "_selftest": {"bad": ["AAA"], "good": ["xAAAx"]}}, "ng"),
        ("正しいルールは通す",
         {"id": "t3", "pattern": "AAA", "_selftest": {"bad": ["zAAAz"], "good": ["BBB"]}}, "ok"),
        ("仕込みが無いものは unknown",
         {"id": "t4", "pattern": "AAA"}, "unknown"),
        ("_skip が文字列だけなら unknown（理由だけでは足りない）",
         {"id": "t7", "pattern": "AAA", "_selftest": {"_skip": "当てられません"}}, "unknown"),
        ("_skip に かわりに が無ければ unknown",
         {"id": "t8", "pattern": "AAA", "_selftest": {"_skip": {"なぜ": "不在検査だから"}}}, "unknown"),
        ("なぜ と かわりに が揃えば declared",
         {"id": "t9", "pattern": "AAA",
          "_selftest": {"_skip": {"なぜ": "不在検査だから", "かわりに": "engine 側で見る"}}}, "declared"),
        ("{{ }} が残っていたら unknown",
         {"id": "t5", "pattern": "x{{ここ}}y", "_selftest": {"bad": ["xy"]}}, "unknown"),
        ("壊れた正規表現は ng",
         {"id": "t6", "pattern": "([", "_selftest": {"bad": ["x"]}}, "ng"),
    ]
    bad = []
    for name, rule, want in cases:
        got, _ = check_rule(rule)
        if got != want:
            bad.append(f"{name}: {want} のはずが {got}")
    if bad:
        for b in bad:
            print(b)
        print(f"NG: 自己検査が {len(bad)} 件落ちました。**この道具が空振りしています。**")
        return 1
    print(f"OK: 自己検査 {len(cases)} 件とも期待どおりでした")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="rules.json の仕込みを当てる")
    ap.add_argument("paths", nargs="*", help="rules.json のパス")
    ap.add_argument("--follow-extends", action="store_true",
                    help="extends を辿って参照先のルールも確かめる")
    ap.add_argument("--self-test", action="store_true", help="この道具自身を確かめる")
    a = ap.parse_args()

    if a.self_test:
        return self_test()
    if not a.paths:
        print("確かめる rules.json を指定してください")
        return 2

    targets: list[Path] = []
    for p in a.paths:
        targets += chain(Path(p)) if a.follow_extends else [Path(p)]
    if a.follow_extends and len(targets) > len(a.paths):
        print(f"参照を辿って {len(targets)} ファイルを確かめます")

    worst = 0
    for p in targets:
        rc = run(Path(p))
        # **1（違反）を 2（確かめられない）より重く見る**
        worst = 1 if 1 in (worst, rc) else max(worst, rc)
    return worst


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # mutation-ok: 例外の帰り道。中からは通せない
        print(f"例外で止まりました: {e}")
        sys.exit(2)
