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
| **スキル本文と食い違った** | 共有の規約はスキルからも消さない（消すと手順から「なぜそうするか」が落ちる）。重複を許す代わりに、引いた文が今もスキルにあるかを見る |
| 同じ id が**別々の規約で重複**していて、**理由が書かれていない** | 1行から2つの規約が出るのは**あり得る**ので落とさない——**ただし理由を書かせる**（`$重複ok`）。2026-09-07、注意のままだった重複が丸1日読まれず、当たっていない根拠が残った |
| `スキルの根拠` の **`文` が空**で、理由も無い | 照合の正本が無いので、スキルと食い違っても気づけない。`$見つからない: "一致 0.35"` は**失敗の記録**であって通してよい理由ではない（同日・同じ形で残った） |
| 上の理由が書いてあるのに、**その注意がもう出ない** | 当たらなくなった宣言（化石）。他の道具と同じ扱い |
| **README の散文の件数**がデータと合っていない | 2026-09-07、規約15 を取り下げたとき `shared-rules.md` と JSON は直したのに **README だけ 22 のまま**残った。同じ日に「散文の数字が腐る」が3件（差分行数・数え方・件数）。**見つからなければ exit 2**（書き方が変わって照合が止まったことを緑にしない） |

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
import re
import sys
import unicodedata
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


def squash(text: str) -> str:
    """空白と全角半角の違いを落とす。**行番号では引かない**（#79 の教訓）。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def check_skill(merge: dict, skill_text: str) -> list[str]:
    """共有の規約が**スキル本文と食い違っていないか**を見る。

    共有の規約はスキルからも消さない（消すと手順から「なぜそうするか」が落ちる）。
    重複を許す代わりに、**引いた文が今もスキルにあるか**を確かめる。
    """
    body = squash(skill_text)
    out = []
    for r in merge.get("確定した共有の規約", []):
        for sn in r.get("スキルの根拠", []):
            if not sn.get("文"):
                # **見つからないと記録されているもの。**
                # 2026-09-07 まではここで素通り（注意）にしていましたが、
                # `$見つからない: "一致 0.35"` は**失敗の記録**であって**通してよい理由ではない**ため、
                # 丸1日読まれずに残りました。**理由を書いてあるときだけ通します。**
                has, why = reason_of(sn, SKILL_OK)
                if has and why:
                    continue
                if has:
                    out.append(f"規約 {r.get('id')}: iOS {sn['iOS']} の `{SKILL_OK}` に"
                               f"**理由がありません**（印だけでは通しません）")
                    continue
                out.append(
                    f"規約 {r.get('id')}: iOS {sn['iOS']} の**文が空です**"
                    f"（照合の正本が無いので、スキルと食い違っても気づけません）\n"
                    f"      スキルを読んで `文` を埋めるか、`{SKILL_OK}` に理由を書いてください\n"
                    f"      記録: {str(sn.get('$見つからない') or '（記録なし）')[:60]}"
                    f"  ← これは**失敗の記録**であって、通してよい理由ではありません")
                continue
            if squash(sn["文"]) not in body:
                out.append(
                    f"規約 {r.get('id')}: スキルの根拠が見つかりません（iOS {sn['iOS']}）\n"
                    f"      探した文: {sn['文'][:70]}\n"
                    f"      規約の文: {str(r.get('規約'))[:70]}")
    return out


#: 注意を「そのまま通してよい」とする理由の置き場（2026-09-07）。
#: 握りつぶし・到達性・変異試験の**行の印と同じ形**を、コードではなくデータに置いたもの。
#: **理由が無ければ落とす。**
#: （ここに印の名前をそのまま書くと、変異試験が**この行を印と読みます**。書きません）
DUP_OK = "$重複ok"        #: 規約の側。値は「なぜ1行が2つの規約を支えてよいか」
SKILL_OK = "$文が無くてよい"  #: `スキルの根拠` の側。値は「なぜ文が無くてよいか」


def reason_of(obj: dict, key: str):
    """(印があるか, 理由) を返す。**理由が空白だけなら「印はあるが理由なし」。**

    `swallow_check` などの行の印とそろえています——**例外は許すが、理由は必ず書かせる。**
    """
    if key not in obj:
        return False, ""
    return True, str(obj.get(key) or "").strip()


#: README の散文に書かれた件数の書き方。**この形以外は見つけられません**（下の 0件 → exit 2）。
#: 生きている件数は**太字**、取り下げた件数は`バッククォート`。
#: 歴史の記述（「12件しか取れませんでした」「2件増えました」）を巻き込まないための区別です
COUNT_LIVE_RX = re.compile(r"\*\*(\d+)\s*件\*\*")
COUNT_DROP_RX = re.compile(r"`(\d+)`\s*件")


def check_readme(merge: dict, readme: str) -> tuple[list[str], int]:
    """README の**散文の件数**が、データと合っているか。`(落とすもの, 見た数)` を返す。

    **なぜ要るか**（2026-09-07・Mac mini の申し出）: 規約15 を取り下げたとき、
    `shared-rules.md` と JSON は直したのに、**README の数字だけ 22 のまま**残った。
    同じ日に「散文の数字が腐る」が3件出ている（差分行数 35 / 数え方 426 対 472 / 件数 22）。
    **どれも検査が見ていない数字だった。**

    **見つからなければ 0 を返す。** 呼ぶ側は 0 のとき exit 2（見ていないのに緑にしない）。
    """
    live = len(merge.get("確定した共有の規約", []))
    drop = len(merge.get("取り下げた規約", []))
    out, seen = [], 0
    for rx, want, label in ((COUNT_LIVE_RX, live, "確定した共有の規約"),
                            (COUNT_DROP_RX, drop, "取り下げた規約")):
        for m in rx.finditer(readme):
            seen += 1
            got = int(m.group(1))
            if got != want:
                line = readme.count("\n", 0, m.start()) + 1
                out.append(f"README:{line} の件数が古いです（書いてある {got} 件 / "
                           f"`{label}` は {want} 件）\n"
                           f"      その辺り: {readme.splitlines()[line - 1][:80]}")
    return out, seen


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

    for r in merge.get("確定した共有の規約", []):
        for sn in r.get("スキルの根拠", []):
            if not sn.get("文"):
                warns.append(f"規約 {r.get('id')}: iOS {sn['iOS']} の文がスキルに見つかりません"
                             f"（{sn.get('$見つからない','')}）。**規約がスキルに書かれていない可能性**")

    # **重複は「あり得る」ので落とさない。ただし理由を書かせる。**
    # `swallow-ok:` などの行の印と同じ扱い（**理由の無い宣言は落とす**）。
    # 2026-09-07: 注意のまま2件が丸1日読まれずに残った（iOS 334 の重複と、規約14 の文）
    dup = {k: n for k, n in seen.items() if n > 1}
    for (side, i), n in dup.items():
        table = ios if side == "iOS" else android
        row = table.get(i, {})
        holders = [r for r in merge.get("確定した共有の規約", [])
                   if i in r.get("ios_ids" if side == "iOS" else "android_ids", [])]
        marked = [(r, *reason_of(r, DUP_OK)) for r in holders]
        given = [(r, why) for r, has, why in marked if has and why]
        empty = [r for r, has, why in marked if has and not why]
        if empty:
            problems.append(
                f"{side} の id {i}: 規約 {', '.join(str(r.get('id')) for r in empty)} の "
                f"`{DUP_OK}` に**理由がありません**（印だけでは通しません）")
        elif not given:
            problems.append(
                f"{side} の id {i} が {n} つの規約（{', '.join(str(r.get('id')) for r in holders)}）の"
                f"根拠になっています。**意図なら、どれかの規約に `{DUP_OK}` で理由を書いてください。**\n"
                f"      その行: {str(row.get('手順'))[:70]}\n"
                f"      （2026-09-07: ここが注意のままだったため、当たっていない根拠が丸1日残りました）")
        else:
            warns.append(f"{side} の id {i} が {n} つの規約の根拠です（理由あり）\n"
                         f"      理由: {given[0][1][:90]}")

    # **化石**: 理由が書いてあるのに、その重複がもう起きていない（当たらなくなった宣言）
    for r in merge.get("確定した共有の規約", []):
        has, why = reason_of(r, DUP_OK)
        if not has:
            continue
        mine = [("iOS", i) for i in r.get("ios_ids", [])] + \
               [("Android", i) for i in r.get("android_ids", [])]
        if not any(k in dup for k in mine):
            problems.append(
                f"規約 {r.get('id')}: `{DUP_OK}` が書いてありますが、**重複はもう起きていません**"
                f"（当たらなくなった宣言。外してください）\n      理由: {why[:70]}")
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

    # ─── 重複: **理由を書けば通す。書かなければ落とす**（2026-09-07） ───────
    # 1行から2規約は意図のこともあるので落としきらない。ただし**注意のままだと読まれない**
    # （同日、注意のままだった重複が丸1日残り、当たっていない根拠が生き延びた）
    def dup2(extra=None):
        r2 = {"id": 2, "ios_ids": [1], "android_ids": [3]}
        if extra is not None:
            r2[DUP_OK] = extra
        return merge({"id": 1, "ios_ids": [1], "android_ids": [2]}, r2)

    T = (tbl(row(1)), tbl(row(2), row(3)))
    # 理由なし → 落とす
    pr, _ = check(dup2(), *T)
    if len([x for x in pr if "つの規約" in x]) != 1:
        print(f"self-test NG: **理由の無い重複が落ちない**（{pr}）"); ok = False
    # 印だけで理由が空 → 落とす（空白だけも同じ）
    for empty in ("", "   "):
        pr, _ = check(dup2(empty), *T)
        if len([x for x in pr if "理由がありません" in x]) != 1:
            print(f"self-test NG: 理由が空（{empty!r}）の印が通った（{pr}）"); ok = False
    # 理由あり → 通す（警告には出す）
    pr, w = check(dup2("記録の作法そのもので、検品と記録の両方を支えるため"), *T)
    if pr:
        print(f"self-test NG: 理由を書いたのに落ちた（{pr}）"); ok = False
    if len([x for x in w if "理由あり" in x]) != 1:
        print(f"self-test NG: 理由ありの重複が警告に出ない（{w}）"); ok = False
    # **化石**: 理由が書いてあるのに重複が起きていない → 落とす
    fossil = merge({"id": 1, "ios_ids": [1], "android_ids": [2], DUP_OK: "むかし重複していた"})
    pr, _ = check(fossil, tbl(row(1)), tbl(row(2)))
    if len([x for x in pr if "もう起きていません" in x]) != 1:
        print(f"self-test NG: **当たらなくなった `{DUP_OK}` が落ちない**（{pr}）"); ok = False

    # スキル本文との食い違い
    sk = merge({"id": 1, "ios_ids": [1], "android_ids": [2],
                "スキルの根拠": [{"iOS": 1, "文": "**verify.sh は1回でよい**"}]})
    if check_skill(sk, "## 手順\n\n**verify.sh は 1 回でよい**\n"):
        print("self-test NG: 空白と全角半角を落とせば一致するのに落ちた"); ok = False
    if len(check_skill(sk, "## 手順\n\n毎回 verify.sh を回す\n")) != 1:
        print("self-test NG: スキルから文が消えたのに落ちない"); ok = False

    # ─── `文` が空: **理由を書けば通す。書かなければ落とす**（2026-09-07） ───
    # それまでは素通り（注意）で、`$見つからない: "一致 0.35"` が**失敗の記録**なのに
    # 「通してよい理由」として働いてしまい、丸1日読まれずに残った
    def empty_sentence(extra=None):
        sn = {"iOS": 1, "文": None, "$見つからない": "一致 0.35"}
        if extra is not None:
            sn[SKILL_OK] = extra
        return merge({"id": 1, "ios_ids": [1], "android_ids": [2], "スキルの根拠": [sn]})

    if len([x for x in check_skill(empty_sentence(), "本文") if "文が空です" in x]) != 1:
        print("self-test NG: **理由の無い空の `文` が落ちない**"); ok = False
    for empty in ("", "  "):
        if len([x for x in check_skill(empty_sentence(empty), "本文") if "理由がありません" in x]) != 1:
            print(f"self-test NG: 理由が空（{empty!r}）の `{SKILL_OK}` が通った"); ok = False
    if check_skill(empty_sentence("iOS 側はスキルではなく道具に書かれているため"), "本文"):
        print("self-test NG: 理由を書いたのに空の `文` で落ちた"); ok = False

    # ─── README の散文の件数（2026-09-07・Mac mini の申し出） ────────────
    # 規約15 を取り下げたとき、README の数字だけ 22 のまま残った。同じ日に
    # 「散文の数字が腐る」が3件（差分行数・数え方・件数）。**どれも検査が見ていなかった**
    mg = merge({"id": 1, "ios_ids": [1], "android_ids": [2]},
               {"id": 2, "ios_ids": [3], "android_ids": [4]})
    mg["取り下げた規約"] = [{"id": 9}]
    OKDOC = "規約は **2件** です。取り下げた分は `1` 件で、末尾に残しています。\n"
    pr, seen = check_readme(mg, OKDOC)
    if pr or seen != 2:
        print(f"self-test NG: 合っている README で落ちた（{pr} / 見た数 {seen}）"); ok = False
    pr, _ = check_readme(mg, OKDOC.replace("**2件**", "**3件**"))
    if len([x for x in pr if "確定した共有の規約" in x]) != 1:
        print(f"self-test NG: **生きている件数のずれが落ちない**（{pr}）"); ok = False
    pr, _ = check_readme(mg, OKDOC.replace("`1` 件", "`5` 件"))
    if len([x for x in pr if "取り下げた規約" in x]) != 1:
        print(f"self-test NG: 取り下げの件数のずれが落ちない（{pr}）"); ok = False
    # **書き方を変えて見つからなくなったら 0 を返す**（呼ぶ側が exit 2 にする）
    _, seen = check_readme(mg, "規約は 2件 です。取り下げた分は 1 件です。\n")
    if seen != 0:
        print(f"self-test NG: **見つからないのに「見た」と言った**（{seen}）"); ok = False
    # 歴史の記述（太字でもバッククォートでもない）を巻き込まない
    _, seen = check_readme(mg, OKDOC + "1回目は 12件 しか取れず、6件を直して 2件 増えました。\n")
    if seen != 2:
        print(f"self-test NG: 歴史の記述まで数えた（{seen}）"); ok = False

    import contextlib, io, tempfile
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        good = (d / "m.json", d / "i.json", d / "a.json")
        good[0].write_text(json.dumps(merge({"id": 1, "ios_ids": [1], "android_ids": [2]})), encoding="utf-8")
        good[1].write_text(json.dumps({"工程一覧": [row(1)]}), encoding="utf-8")
        good[2].write_text(json.dumps({"工程一覧": [row(2)]}), encoding="utf-8")
        rmd = d / "README.md"
        rmd.write_text("規約は **1件** です。取り下げた分は `0` 件です。\n", encoding="utf-8")
        argv = ["--merge", str(good[0]), "--ios", str(good[1]), "--android", str(good[2]),
                "--readme", str(rmd)]
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

        # **README の書き方が変わって件数が見つからなくなったら exit 2**（緑にしない）
        good[0].write_text(json.dumps(merge({"id": 1, "ios_ids": [1], "android_ids": [2]})), encoding="utf-8")
        rmd.write_text("規約は 1件 です。取り下げた分は 0 件です。\n", encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = main(argv)
        if rc != 2:
            print(f"self-test NG: **README の件数が見つからないのに exit {rc}**（期待 2）"); ok = False

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
    ap.add_argument("--skill", type=Path,
                    default=Path.home() / ".claude/skills/flutter-ios-build-check/SKILL.md",
                    help="共有の規約と食い違っていないかを見るスキル本文")  # reachability-ok: 引数の既定値。実行時に読むのは --skill で差し替えられる
    ap.add_argument("--readme", type=Path, default=Path(__file__).resolve().parent / "README.md",
                    help="散文の件数を照合する README")
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
    readme_seen = None
    if args.readme.exists():
        rp, readme_seen = check_readme(merge, args.readme.read_text(encoding="utf-8"))
        problems += rp
    else:
        warns.append(f"README がありません（{args.readme}）。**散文の件数は見ていません**")
    if args.skill.exists():
        problems += check_skill(merge, args.skill.read_text(encoding="utf-8"))
    else:
        warns.append(f"スキル本文がありません（{args.skill}）。**食い違いは見ていません**")
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
    if readme_seen == 0:
        # **0件は「綺麗」ではなく「見ていない」。** README の書き方が変わると、
        # 件数の照合が黙って止まります（それを緑で返さない）
        print(f"{args.readme} に件数の記述が1つも見つかりません。**件数を確かめていません。**\n"
              f"  生きている件数は `**21件**` のように**太字**、取り下げた件数は "
              f"`` `1` 件 `` のようにバッククォートで書いてください。\n"
              f"  （歴史の記述と区別するための決まりです。書き方を変えるなら "
              f"`COUNT_LIVE_RX` / `COUNT_DROP_RX` も直してください）", file=sys.stderr)
        return 2
    n = len(merge.get("確定した共有の規約", []))
    print(f"共有の規約 {n} 件。根拠はすべて実在し、両側とも `none` です"
          f"（README の件数 {readme_seen} 箇所も一致）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
