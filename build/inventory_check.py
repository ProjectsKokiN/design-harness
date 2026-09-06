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
| `依存` が none 以外なのに `依存の理由` が空 | 「Windows だから」で分けると、統合できるものまで分かれる |
| `検証状態` が `measured` なのに `出典` が空 | 測ったと言い切るなら、どこを見たか要る |
| `id` の重複 | 突き合わせの鍵に使う |

## 捕まえないもの

- **書いてある内容が正しいか。** 手順が実際に動くかは見ない（それは各機体の責任）
- **統合すべきかどうか。** ここは形だけ。判定は両方が揃ってから
- 確かめた方法: `--self-test`（各違反が1件ずつ落ちること・正しい形が通ること・
  違反時に exit 1 で落ちること）
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


def check(doc: dict, schema: dict) -> list[str]:
    """違反を**行番号ではなく id で**返す（行番号はすぐ古くなる。#79 の教訓）。"""
    problems: list[str] = []
    stages = set(schema["工程"]["値"])
    deps = set(schema["依存"]["値"])
    states = set(schema["検証状態"]["値"])
    required = schema["必須の列"]

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

        st = r.get("工程")
        if st is not None and st not in stages:
            problems.append(f"id {rid}: `工程` が語彙の外です（{st}）。使える語: {'/'.join(sorted(stages))}")

        dep = r.get("依存")
        if dep is not None and dep not in deps:
            problems.append(f"id {rid}: `依存` が語彙の外です（{dep}）。使える語: {'/'.join(sorted(deps))}")
        elif dep is not None and dep != "none" and not str(r.get("依存の理由", "")).strip():
            problems.append(
                f"id {rid}: `依存` が {dep} なのに `依存の理由` が空です"
                "（何に縛られているかを具体で。『Windows だから』は理由になりません）")

        vs = r.get("検証状態")
        if vs is not None and vs not in states:
            problems.append(f"id {rid}: `検証状態` が語彙の外です（{vs}）")
        elif vs == "measured" and not str(r.get("出典", "")).strip():
            problems.append(f"id {rid}: `measured` なのに `出典` が空です（測ったなら、どこを見たか要ります）")

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
        ("落とす: 依存が語彙の外", {"工程一覧": [row(依存="windows")]}, 1),
        ("落とす: 依存が none 以外で理由が空", {"工程一覧": [row(依存="env")]}, 1),
        ("通る: 依存に理由がある", {"工程一覧": [row(依存="env", 依存の理由="cp932 の端末で print が死ぬ")]}, 0),
        ("落とす: measured なのに出典が空", {"工程一覧": [row(検証状態="measured", 出典="")]}, 1),
        ("落とす: id の重複（2 行目で1件）", {"工程一覧": [row(id=1), row(id=1)]}, 1),
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
    dep_none = sum(1 for r in doc["工程一覧"] if r.get("依存") == "none")
    print(f"{args.file}: {n} 行。形は項目表どおりです。")
    print(f"  うち 依存=none は {dep_none} 行（統合の候補。判定は両機体が揃ってから）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
