#!/usr/bin/env python3
"""突き合わせの結果が**根拠を失っていないか**を見る（2026-09-06 新設）。

## なぜ要るか

共有の規約（`build/shared-rules.md`）は、両機体の棚卸しの**行 id を根拠に引いています**。
片方が行を直すと、**引いた先が別の主張に変わっても誰も気づきません。**

実害（2026-09-06・この日のうちに起きた）:

> Windows が Android 104（5つの主張を1行に束ねていた）を分割し、199 / 200 / 201 を新設した。
> 規約4「依頼に書かれた項目だけを見る」と規約5「試験がある項目は画面で見ない」は
> **104 を根拠に引いていた**が、その文は 199 と 200 へ移った。104 は
> 「報告に『見たこと』を表で書く」という別の主張になった。
> **2つの規約が、根拠が抜けたまま緑で残っていた。**

行 id は**動く**。動いたことを機械で見ないと、規約は根拠を失ったまま生き残る。

## 何を見るか

    python3 build/merge_check.py
    python3 build/merge_check.py --self-test

| 落とす | なぜ |
|---|---|
| 根拠の id が棚卸しに**存在しない** | 行が消えた。規約は宙に浮いている |
| 根拠の id の `依存` が `none` **でない** | 共有できない行を根拠にしている（統合の前提が崩れている） |
| 根拠が**片側だけ** | 「両方で成り立つ」と言えない。片側の規約は各プラットフォームのスキルへ |
| 根拠の行の**中身が変わった** | id は生きているのに主張が別物になった。**上の実害がまさにこれ** |
| 同じ id が**別々の規約で重複** | 1行から2つの規約が出ているので、意図か事故かを人が確かめる（警告） |

**id の実在だけを見ても、上の実害は捕まりません。** 104 は消えていないし `none` のままで、
**中身だけが変わった**からです。そこで各規約に `根拠の指紋`（引いた行の `手順` の短い
ハッシュ）を持たせ、**引いた先の文が変わったら落とします**。

    python3 build/merge_check.py --stamp    # いまの中身で指紋を押し直す（人が確かめたあとに打つ）

## 捕まえないもの

- **規約の文が正しいか。** 指紋が変わったことは分かるが、**新しい文でも規約が成り立つか**は
  人が読んで決める（だから落としたときに新旧の `手順` を並べて出す）
- **指紋を押し直すのが正しいか。** `--stamp` は人が確かめたあとに打つもので、
  **赤を消すために打つと検査が空振りになる**
- 確かめた方法: `--self-test`（4つの違反それぞれが落ちること・正しい形が通ること・
  違反時に exit 1・読めない入力で exit 2）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "tools"))
try:
    import _utf8  # noqa: F401
except ImportError:
    pass

MERGE = ROOT / "analysis" / "merge-build-2026-09-06.json"
IOS = ROOT / "analysis" / "build-ios-2026-09-06.json"
AND = ROOT / "analysis" / "build-android-2026-09-06.json"


def index(doc: dict) -> dict:
    return {r["id"]: r for r in doc.get("工程一覧", [])}


def fingerprint(row: dict) -> str:
    """根拠の行の**主張**の指紋。`手順` だけを見る（実体や出典は動いてよい）。"""
    return hashlib.sha256(str(row.get("手順", "")).encode("utf-8")).hexdigest()[:12]


def check(merge: dict, ios: dict, android: dict) -> tuple[list[str], list[str]]:
    """(落とすもの, 警告) を返す。**規約の id で報告する**（行番号は動く）。"""
    problems: list[str] = []
    warns: list[str] = []
    seen = Counter()

    for r in merge.get("確定した共有の規約", []):
        rid = r.get("id")
        for side, ids, table in (("iOS", r.get("ios_ids", []), ios),
                                 ("Android", r.get("android_ids", []), android)):
            if not ids:
                problems.append(f"規約 {rid}: {side} の根拠がありません（片側だけの規約は共有層に置けません）")
                continue
            for i in ids:
                seen[(side, i)] += 1
                row = table.get(i)
                if row is None:
                    problems.append(f"規約 {rid}: {side} の根拠 id {i} が棚卸しにありません（行が消えた）")
                    continue
                if row.get("依存") != "none":
                    problems.append(
                        f"規約 {rid}: {side} の根拠 id {i} の `依存` が `{row.get('依存')}` です"
                        f"（`none` でない行を根拠にしています）\n"
                        f"      その行: {str(row.get('手順'))[:70]}")
                    continue
                stamped = (r.get("根拠の指紋") or {}).get(f"{side}:{i}")
                now = fingerprint(row)
                if stamped is None:
                    warns.append(f"規約 {rid}: {side} の id {i} に指紋がありません"
                                 f"（`--stamp` で押してください。押すまで中身の変化は見られません）")
                elif stamped != now:
                    problems.append(
                        f"規約 {rid}: {side} の根拠 id {i} の**中身が変わりました**"
                        f"（指紋 {stamped} → {now}）\n"
                        f"      いまの行: {str(row.get('手順'))[:70]}\n"
                        f"      規約の文: {str(r.get('規約'))[:70]}")

    for (side, i), n in seen.items():
        if n > 1:
            table = ios if side == "iOS" else android
            row = table.get(i, {})
            warns.append(f"{side} の id {i} が {n} つの規約の根拠になっています"
                         f"（1行から2つの規約が出ています。意図か事故かを確かめてください）\n"
                         f"      その行: {str(row.get('手順'))[:70]}")
    return problems, warns


def self_test() -> int:
    ok = True

    def tbl(*rows):
        return {r["id"]: r for r in rows}

    def row(i, dep="none", te="手順 " + "x"):
        return {"id": i, "依存": dep, "手順": te}

    def merge(*rules):
        return {"確定した共有の規約": list(rules)}

    CASES = [
        ("通る: 両側の根拠が none",
         merge({"id": 1, "ios_ids": [1], "android_ids": [2]}),
         tbl(row(1)), tbl(row(2)), 0),
        ("落とす: iOS の根拠が消えた",
         merge({"id": 1, "ios_ids": [9], "android_ids": [2]}),
         tbl(row(1)), tbl(row(2)), 1),
        ("落とす: Android の根拠が none でない",
         merge({"id": 1, "ios_ids": [1], "android_ids": [2]}),
         tbl(row(1)), tbl(row(2, dep="platform")), 1),
        ("落とす: 片側の根拠が空",
         merge({"id": 1, "ios_ids": [1], "android_ids": []}),
         tbl(row(1)), tbl(row(2)), 1),
        ("落とす: 両側とも空（2件）",
         merge({"id": 1, "ios_ids": [], "android_ids": []}),
         tbl(row(1)), tbl(row(2)), 2),
    ]
    for name, mg, i, a, want in CASES:
        got = len(check(mg, i, a)[0])
        if got != want:
            print(f"self-test NG: {name} → 違反 {got} 件（期待 {want}）"); ok = False

    # **中身が変わったら落とす**（id は生きているのに主張が別物になった型・2026-09-06 の実害）
    changed = merge({"id": 1, "ios_ids": [1], "android_ids": [2],
                     "根拠の指紋": {"iOS:1": fingerprint(row(1)), "Android:2": "0" * 12}})
    if len(check(changed, tbl(row(1)), tbl(row(2)))[0]) != 1:
        print("self-test NG: 根拠の中身が変わったのに落ちない"); ok = False
    same = merge({"id": 1, "ios_ids": [1], "android_ids": [2],
                  "根拠の指紋": {"iOS:1": fingerprint(row(1)), "Android:2": fingerprint(row(2))}})
    if check(same, tbl(row(1)), tbl(row(2)))[0]:
        print("self-test NG: 指紋が一致しているのに落ちた"); ok = False
    # 指紋が無いものは**警告**（押していないだけ）
    if not check(merge({"id": 1, "ios_ids": [1], "android_ids": [2]}), tbl(row(1)), tbl(row(2)))[1]:
        print("self-test NG: 指紋が無いのに警告が出ない"); ok = False

    # 重複は**警告**であって落とさない（1行から2規約は意図のこともある）
    mg = merge({"id": 1, "ios_ids": [1], "android_ids": [2]},
               {"id": 2, "ios_ids": [1], "android_ids": [3]})
    p, w = check(mg, tbl(row(1)), tbl(row(2), row(3)))
    if p:
        print(f"self-test NG: 重複で落ちてしまった（{p}）"); ok = False
    dup = [x for x in w if "つの規約の根拠" in x]
    if len(dup) != 1:
        print(f"self-test NG: 重複の警告が {len(dup)} 件（期待 1）"); ok = False

    import contextlib, io, tempfile
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        good = (d / "m.json", d / "i.json", d / "a.json")
        good[0].write_text(json.dumps(merge({"id": 1, "ios_ids": [1], "android_ids": [2]})), encoding="utf-8")
        good[1].write_text(json.dumps({"工程一覧": [row(1)]}), encoding="utf-8")
        good[2].write_text(json.dumps({"工程一覧": [row(2)]}), encoding="utf-8")
        argv = ["--merge", str(good[0]), "--ios", str(good[1]), "--android", str(good[2])]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = main(argv)
        if rc != 0:
            print(f"self-test NG: 違反が無いのに exit {rc}（期待 0）"); ok = False

        good[0].write_text(json.dumps(merge({"id": 1, "ios_ids": [9], "android_ids": [2]})), encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = main(argv)
        if rc != 1:
            print(f"self-test NG: 違反があるのに exit {rc}（期待 1）"); ok = False

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = main(["--merge", str(d / "no-such.json"), "--ios", str(good[1]), "--android", str(good[2])])
        if rc != 2:
            print(f"self-test NG: 読めない入力で exit {rc}（期待 2）"); ok = False

    if ok:
        print("self-test: OK")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--merge", type=Path, default=MERGE)
    ap.add_argument("--ios", type=Path, default=IOS)
    ap.add_argument("--android", type=Path, default=AND)
    ap.add_argument("--stamp", action="store_true",
                    help="いまの中身で指紋を押し直す（**人が確かめたあとに打つ**）")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    try:
        merge = json.loads(args.merge.read_text(encoding="utf-8"))
        ios = index(json.loads(args.ios.read_text(encoding="utf-8")))
        android = index(json.loads(args.android.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as e:
        print(f"読めません: {e}", file=sys.stderr)
        return 2

    if args.stamp:
        for r in merge.get("確定した共有の規約", []):
            fp = {}
            for side, ids, table in (("iOS", r.get("ios_ids", []), ios),
                                     ("Android", r.get("android_ids", []), android)):
                for i in ids:
                    if i in table:
                        fp[f"{side}:{i}"] = fingerprint(table[i])
            r["根拠の指紋"] = fp
        args.merge.write_text(json.dumps(merge, ensure_ascii=False, indent=1), encoding="utf-8")
        n = sum(len(r.get("根拠の指紋", {})) for r in merge.get("確定した共有の規約", []))
        print(f"指紋を押しました（規約 {len(merge.get('確定した共有の規約', []))} 件・根拠 {n} 本）。")
        return 0

    problems, warns = check(merge, ios, android)
    for w in warns:
        print(f"  注意: {w}")
    if problems:
        print("共有の規約が根拠を失っています。", file=sys.stderr)
        print("**片方が行を直すと、引いた先が別の主張に変わっても気づけません**"
              "（2026-09-06 に規約4・5 で実際に起きました）。", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        print("\n  根拠の id を付け替えるか、規約を取り下げてください。", file=sys.stderr)
        return 1
    n = len(merge.get("確定した共有の規約", []))
    print(f"共有の規約 {n} 件。根拠はすべて実在し、両側とも `none` です。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
