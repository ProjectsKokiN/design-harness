#!/usr/bin/env python3
"""ビルドの棚卸しが**項目表どおりの形か**を見る（2026-09-06 新設）。

## なぜ要るか

Mac mini（iOS）と Windows（Android）が**別々に**ビルドの実態を書き出し、
**両方が揃ってから統合の可否を決めます**。突き合わせを機械でやるには、
2つのファイルの**列が揃っている**必要があります。

2026-09-06 の機体分析（78件）は `.md` と `.json` の対で出したので項目単位で
突き合わせられました。**散文だけだと読み手が解釈し直すことになり、
統合の判定が人の印象になります。** この道具はその形を守るためだけにあります。

## 何を見るか

    python3 build/inventory_check.py analysis/build-android-2026-09-06.json
    python3 build/inventory_check.py --self-test

| 落とす | なぜ |
|---|---|
| 必須の列が無い | 突き合わせのときに片側だけ空欄になる |
| `工程` が語彙の外 | 行が対応しなくなる（iOS の「検品」と Android の「検証」が別物になる） |
| `依存` が語彙の外 | **統合の判定はこの列だけで決まる**ので、崩れると判定できない |
| `案件差` が語彙の外 | どの案件に効くかが機械で読めない（iOS には PlantTalk がある） |
| `案件差` が `差あり` なのに中身が空 | 「違う」だけ書かれても、どう違うかが残らない |
| 列の型が違う | `所要: "はやい"` が通ると、秒として比べられない（#85） |
| `依存` が none 以外なのに `依存の理由` が空 | 「Windows だから」で分けると、統合できるものまで分かれる |
| `検証状態` が `measured` なのに `出典` が空 | 測ったと言い切るなら、どこを見たか要る |
| `id` の重複 | 突き合わせの鍵に使う |

**何を見るかは項目表の `列の規約` から導きます**（型・語彙・条件で必須になる列）。
**この道具に一覧を持たせません。** 列を足すときは項目表に足せば、ここは触らずに検査が当たります
（issue #85: 検査が宣言に追いついておらず、`所要` の型が素通りしていた）。

## 捕まえないもの

- **書いてある内容が正しいか。** 手順が実際に動くかは見ない（それは各機体の責任）
- **統合すべきかどうか。** ここは形だけ。判定は両方が揃ってから
- 確かめた方法: `--self-test`（各違反が1件ずつ落ちること・正しい形が通ること・
  違反時に exit 1・読めない入力で exit 2 で落ちること）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
try:
    import _utf8  # noqa: F401  出力の文字コードで死なない
except ImportError:  # 単体で持ち出したときも動く
    pass

SCHEMA = HERE / "inventory-schema.json"


def _load_schema() -> dict:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def _type_ok(value, spec: str) -> bool:
    """`列の規約.型` の1語に当てる。`|` で並べたどれかに当たれば通る。"""
    for want in spec.split("|"):
        want = want.strip()
        if want == "null" and value is None:
            return True
        if want == "int" and isinstance(value, int) and not isinstance(value, bool):
            return True
        if want == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
            return True
        if want == "str" and isinstance(value, str):
            return True
    return False


def check(doc: dict, schema: dict) -> list[str]:
    """違反を**行番号ではなく id で**返す（行番号はすぐ古くなる。#79 の教訓）。

    **検査の一覧は持たない。** 何を見るかは `列の規約` から導く（issue #85）。
    列を足すときは項目表に足せば、ここは触らずに検査が当たる。
    """
    problems: list[str] = []
    required = schema["必須の列"]
    rule = schema["列の規約"]
    types = rule["型"]
    vocab = {col: set(schema[sec]["値"]) for col, sec in rule["語彙のある列"].items()}
    conds = rule["条件で必須になる列"]

    rows = doc.get("工程一覧")
    if not isinstance(rows, list):
        return ["ルートに `工程一覧`（配列）がありません"]
    if not rows:
        return ["`工程一覧` が空です（無いなら .md に理由を書いてから空にしてください）"]

    seen: set = set()
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            problems.append(f"{i} 番目が辞書ではありません")
            continue
        rid = r.get("id", f"（id 無し・{i} 番目）")
        if rid in seen:
            problems.append(f"id {rid}: 重複しています（突き合わせの鍵に使います）")
        seen.add(rid)

        for col in required:
            if col not in r:
                problems.append(f"id {rid}: 必須の列 `{col}` がありません")

        # 型（**宣言から導く**。ここを飛ばすと `所要: \"はやい\"` が素通りする・#85）
        for col, spec in types.items():
            if col in r and not _type_ok(r[col], spec):
                problems.append(
                    f"id {rid}: `{col}` の型が違います（{r[col]!r} · 期待 {spec}）")

        # 語彙
        bad_vocab = set()
        for col, allowed in vocab.items():
            v = r.get(col)
            if v is not None and isinstance(v, str) and v not in allowed:
                bad_vocab.add(col)
                problems.append(
                    f"id {rid}: `{col}` が語彙の外です（{v}）。"
                    f"使える語: {'/'.join(sorted(allowed))}")

        # 条件で必須になる列。
        # **語彙の外だった列では見ない。** 根が1つなのに2件報告すると、直す人が
        # 2か所直そうとする（同じ形の二重判定を machine_scope で1度やっている・#29）
        for c in conds:
            col, want, need = c["列"], c["が"], c["要る列"]
            v = r.get(col)
            if v is None or col in bad_vocab:
                continue
            hit = (v != want.split()[0]) if want.endswith("以外") else (v == want)
            if hit and not str(r.get(need, "")).strip():
                problems.append(
                    f"id {rid}: `{col}` が {want} なのに `{need}` が空です（{c['なぜ']}）")

    return problems


def self_test() -> int:
    schema = _load_schema()
    ok = True

    def row(**kw):
        base = dict(id=1, 工程="ビルド", 手順="release を作る", 実体="flutter build apk",
                    依存="none", 案件差="両方", 所要=None, 出典="実測", 検証状態="read")
        base.update(kw)
        return base

    CASES = [
        ("通る: 正しい行", {"工程一覧": [row()]}, 0),
        ("落とす: 必須の列が無い", {"工程一覧": [{k: v for k, v in row().items() if k != "所要"}]}, 1),
        ("落とす: 工程が語彙の外", {"工程一覧": [row(工程="コンパイル")]}, 1),
        # 語彙の外のときは条件必須を重ねて報告しない（根が1つなので1件）
        ("落とす: 依存が語彙の外（理由が空でも1件）", {"工程一覧": [row(依存="windows")]}, 1),
        ("落とす: 依存が none 以外で理由が空", {"工程一覧": [row(依存="env")]}, 1),
        ("通る: 依存に理由がある", {"工程一覧": [row(依存="env", 依存の理由="cp932 の端末で print が死ぬ")]}, 0),
        ("落とす: measured なのに出典が空", {"工程一覧": [row(検証状態="measured", 出典="")]}, 1),
        ("落とす: id の重複（2 行目で1件）", {"工程一覧": [row(id=1), row(id=1)]}, 1),
        ("通る: platform に理由がある", {"工程一覧": [row(依存="platform", 依存の理由="TestFlight 版と development 署名版は入れ替えられない")]}, 0),
        ("落とす: platform なのに理由が空", {"工程一覧": [row(依存="platform")]}, 1),
        ("通る: 案件差 planttalk", {"工程一覧": [row(案件差="planttalk")]}, 0),
        ("落とす: 案件差が語彙の外", {"工程一覧": [row(案件差="qnd")]}, 1),
        ("落とす: 差あり なのに中身が空", {"工程一覧": [row(案件差="差あり")]}, 1),
        ("通る: 差あり に中身がある", {"工程一覧": [row(案件差="差あり", 案件差の中身="aub=A / flash=B")]}, 0),
        # **型**（#85: `所要: "はやい"` が素通りしていた）
        ("落とす: 所要が文字列", {"工程一覧": [row(所要="はやい")]}, 1),
        ("通る: 所要が数値", {"工程一覧": [row(所要=90)]}, 0),
        ("通る: 所要が null", {"工程一覧": [row(所要=None)]}, 0),
        ("落とす: id が文字列", {"工程一覧": [row(id="いち")]}, 1),
        ("落とす: 手順が数値", {"工程一覧": [row(手順=1)]}, 1),
        ("落とす: 所要が真偽値", {"工程一覧": [row(所要=True)]}, 1),
        ("落とす: 工程一覧が無い", {"事例": []}, 1),
        ("落とす: 工程一覧が空", {"工程一覧": []}, 1),
    ]
    for name, doc, want in CASES:
        got = len(check(doc, schema))
        if got != want:
            print(f"self-test NG: {name} → 違反 {got} 件（期待 {want}）")
            ok = False

    # **違反があるときに exit 1 で落ちるか**を main() ごと確かめる
    import contextlib, io, tempfile
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "x.json"
        f.write_text(json.dumps({"工程一覧": [row(工程="コンパイル")]}, ensure_ascii=False),
                     encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = main([str(f)])
        if rc != 1:
            print(f"self-test NG: 違反があるのに exit {rc}（期待 1）"); ok = False

        f.write_text(json.dumps({"工程一覧": [row()]}, ensure_ascii=False), encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = main([str(f)])
        if rc != 0:
            print(f"self-test NG: 違反が無いのに exit {rc}（期待 0）"); ok = False

        # **読めない入力で 2 を返すか**をここで見る。
        # attack/broken_input_test.py は `tools/*.py` の `--config` を持つ道具しか走査しない
        # ので、この道具（build/ 配下・位置引数）には届かない。**届かない試験を根拠に
        # 変異試験の除外を書くと、除外そのものが空振りになる**（2026-09-06 に実際そうなった）
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = main([str(Path(td) / "no-such-file.json")])
        if rc != 2:
            print(f"self-test NG: 無いファイルで exit {rc}（期待 2）"); ok = False

        broken = Path(td) / "broken.json"
        broken.write_text("{壊れている", encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = main([str(broken)])
        if rc != 2:
            print(f"self-test NG: 壊れた JSON で exit {rc}（期待 2）"); ok = False

    if ok:
        print("self-test: OK")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", nargs="?", type=Path, help="analysis/build-<platform>-<日付>.json")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()
    if args.file is None:
        ap.error("棚卸しのファイルを指定してください（--self-test でも可）")

    try:
        doc = json.loads(args.file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"読めません: {e}", file=sys.stderr)
        return 2

    problems = check(doc, _load_schema())
    if problems:
        print(f"{args.file}: 項目表に合っていません。", file=sys.stderr)
        print("**このままだと、もう一方の機体と突き合わせられません**"
              "（列が揃わないと機械で比べられません）。", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        print("\n  項目表: build/inventory-schema.json", file=sys.stderr)
        return 1

    n = len(doc["工程一覧"])
    from collections import Counter
    c = Counter(r.get("依存") for r in doc["工程一覧"])
    print(f"{args.file}: {n} 行。形は項目表どおりです。")
    print(f"  依存=none {c['none']} 行（統合の候補）／platform {c['platform']} 行"
          f"（**統合しない**・そのプラットフォームのスキルへ）")
    print(f"  env {c['env']} / hardware {c['hardware']} / credential {c['credential']} / project {c['project']}")
    print("  判定は両機体が揃ってから当てます（build/README.md）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
