#!/usr/bin/env python3
"""**文書のコード例が、自分の禁止ルールに違反していないか**を見る（2026-09-18 新設）。

## なぜ要るか

2026-09-18、同じスキルの中で**2つの文書が逆のことを言っていました。**

| 文書 | 言っていたこと |
|---|---|
| `PLAN.md` | 実装は `.primary` `.secondary` を使う（OS に決めさせる） |
| `token-pipeline-swift.md` | セマンティックカラーを `Color(light:dark:)` で**生成する** |

後者のとおりに作ると、**その時点の iOS の実測値が焼き付き、利用者が
ダークモードやコントラストの設定を変えてもそこだけ追従しません。**

**別セッションの指摘で見つかりました。機械では見ていませんでした。**

## 見るもの

文書の**コード例**を取り出し、その案件の `rules.json` の禁止パターンを当てます。
**文書が禁止しているものを、文書自身が手本として見せていたら違反**です。

## 捕まえないもの

- **「やってはいけない」と印を付けた例**。悪い例を並べるのは正しい書き方なので通します
  （印: やってはいけない / 空振り / 悪い例 / 間違い / 禁止 / 使わない / 避ける / NG / だめ）
- **散文の中の記述。**コードブロックの中だけを見ます
- 文書どうしの矛盾そのもの。**コード例に現れた矛盾だけ**を見ます

## 終了コード

  0 … コード例を見て、印の無い違反が無かった
  1 … 印の無い違反があった
  2 … 確かめられなかった（コード例が1つも無い・rules.json が読めない）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

FENCE_RX = re.compile(r"^([ \t]*)```+[ \t]*([A-Za-z0-9_+-]*)[ \t]*$")

# 拡張子 → コードブロックの言語名
LANG = {
    ".dart": {"dart"},
    ".swift": {"swift"},
    ".ts": {"ts", "typescript", "tsx"},
    ".tsx": {"tsx", "typescript"},
    ".js": {"js", "javascript", "jsx"},
}

# **悪い例だと分かる印。** これがあれば通す
BAD_MARK_RX = re.compile(
    r"やってはいけない|してはいけない|空振り|悪い例|間違い|禁止|使わない|使わ(?:ず|ない)|"
    r"避ける|避けて|\bNG\b|だめ|ダメ|しないで|書かない|通りません|落ちます")

PLACEHOLDER = re.compile(r"\{\{.*?\}\}", re.S)


def blocks(text: str, langs: set[str]):
    """(開始行, 言語, 中身, 直前の3行) を返す。**入れ子の柵に注意する。**"""
    lines = text.splitlines()
    out, i = [], 0
    while i < len(lines):
        m = FENCE_RX.match(lines[i])
        if not m:
            i += 1
            continue
        indent, lang = m.group(1), (m.group(2) or "").lower()
        start, body = i, []
        i += 1
        while i < len(lines):
            m2 = FENCE_RX.match(lines[i])
            if m2 and m2.group(1) == indent and not m2.group(2):
                break
            body.append(lines[i])
            i += 1
        i += 1
        if lang in langs:
            before = "\n".join(lines[max(0, start - 3):start])
            out.append((start + 1, lang, "\n".join(body), before))
    return out


def load_rules(path: Path):
    """`rules.json` から、当てられる（置き換え記法が残っていない）ルールを返す。"""
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    exts = [e if e.startswith(".") else "." + e
            for e in (data.get("file_extensions") or [".dart"])]
    langs: set[str] = set()
    for e in exts:
        langs |= LANG.get(e, set())
    rules, scoped = [], []
    for r in data.get("rules") or []:
        pat = r.get("pattern")
        if not r.get("id") or not pat or PLACEHOLDER.search(pat):
            continue
        if r.get("type") == "require-near":
            continue
        # **`paths` を持つルールは当てません。** そのルールは特定の置き場でだけ効きます。
        # 文書のコード例に置き場はないので、当てると**テーマ層の正しい手本を咎めます**
        # （2026-09-18、実際に `no-primitive-in-ui` が生成物の例を咎めました）。
        # **見ていないことは出します。**
        if r.get("paths"):
            scoped.append(r["id"])
            continue
        try:
            rules.append((r["id"], re.compile(pat, re.S if r.get("multiline") else 0),
                          r.get("forbidden", ""), r.get("instead", "")))
        except re.error:
            continue  # mutation-ok: 壊れた正規表現は rules_selftest が咎める
    return rules, langs, scoped


def run(docs: Path, rules_path: Path) -> int:
    try:
        rules, langs, scoped = load_rules(rules_path)
    except Exception as e:
        print(f"ルールが読めません: {rules_path} — {e}")
        return 2
    if not rules:
        print(f"当てられるルールがありません: {rules_path}")
        return 2
    if not langs:
        print(f"見るべきコードブロックの言語が決まりません: {rules_path}")
        return 2

    md = sorted(docs.rglob("*.md")) if docs.is_dir() else [docs]
    seen = bad = marked = 0
    lines_out = []
    for f in md:
        text = f.read_text(encoding="utf-8", errors="replace")
        for ln, lang, body, before in blocks(text, langs):
            seen += 1
            ctx = before + "\n" + body
            for rid, rx, forbidden, instead in rules:
                m = rx.search(body)
                if not m:
                    continue
                if BAD_MARK_RX.search(ctx):
                    marked += 1
                    continue
                bad += 1
                try:
                    rel = f.relative_to(docs if docs.is_dir() else docs.parent)
                except ValueError:
                    rel = f
                lines_out.append(
                    f"  {rel}:{ln} [{rid}] 手本のコード例が、自分の禁止に当たっています\n"
                    f"      当たった所: {m.group(0)[:60]!r}\n"
                    f"      禁止: {forbidden}\n"
                    f"      代替: {instead[:100]}")

    for l in lines_out:
        print(l)
    tail = (f"コード例 {seen} 件（{'/'.join(sorted(langs))}）/ "
            f"印の無い違反 {bad} 件 / 悪い例として印あり {marked} 件")
    if scoped:
        print(f"注意: 置き場が決まったルール {len(scoped)} 件は当てていません"
              f"（{', '.join(scoped)}）。**文書のコード例に置き場はありません**")
    if bad:
        print(f"NG: {tail}。**文書が禁止しているものを、文書自身が手本にしています。**\n"
              f"  直すか、「やってはいけない」と分かる印を添えてください")
        return 1
    if seen == 0:
        print(f"確かめられません: コード例が1つもありません（{'/'.join(sorted(langs))}）。"
              f"**0件は「綺麗」ではなく「見ていない」です**")
        return 2
    print(f"OK: {tail}")
    return 0


def self_test() -> int:
    import tempfile
    bad = []

    def case(name, got, want):
        if got != want:
            bad.append(f"{name}: {want} のはずが {got}")

    rules = {"file_extensions": [".swift"],
             "rules": [{"id": "no-raw-color", "pattern": r"Color\(\s*red\s*:",
                        "forbidden": "生の色", "instead": "Sem.* を使う"},
                       {"id": "ph", "pattern": r"x{{ここ}}y"}]}
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        root = Path(d)
        rp = root / "rules.json"
        rp.write_text(json.dumps(rules), encoding="utf-8")
        doc = root / "a.md"

        import contextlib, io

        def run_doc(src):
            doc.write_text(src, encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = run(root, rp)
            return rc, buf.getvalue()

        # 1. **印の無い違反を捕まえる**
        rc, out = run_doc("こう書きます。\n\n```swift\nColor(red: 1, green: 0, blue: 0)\n```\n")
        case("印の無い違反", rc, 1)
        if "no-raw-color" not in out:
            bad.append("違反にルールの名前が出ていません")

        # 2. **印があれば通す**（悪い例を並べるのは正しい書き方）
        rc, _ = run_doc("**やってはいけない書き方**です。\n\n"
                        "```swift\nColor(red: 1, green: 0, blue: 0)\n```\n")
        case("印あり", rc, 0)

        # 3. 印がブロックの中にあってもよい
        rc, _ = run_doc("```swift\n// **使わない**\nColor(red: 1, green: 0, blue: 0)\n```\n")
        case("ブロック内の印", rc, 0)

        # 4. 違反が無ければ通す
        rc, _ = run_doc("```swift\nSem.accentDefault\n```\n")
        case("違反なし", rc, 0)

        # 5. **別の言語のブロックは見ない**
        rc, _ = run_doc("```dart\nColor(red: 1)\n```\n")
        case("別の言語", rc, 2)

        # 6. コード例が無ければ 2（0件を「綺麗」と言わない）
        rc, _ = run_doc("ただの散文です。`Color(red: 1)` と書いても見ません。\n")
        case("コード例なし", rc, 2)

        # 7. 置き換え記法が残るルールは当てない
        rc, _ = run_doc("```swift\nlet a = x{{ここ}}y\n```\n")
        case("置き換え記法", rc, 0)

        # 8. **`paths` を持つルールは当てない**（2026-09-18・実際に誤検出した）
        rp.write_text(json.dumps({"file_extensions": [".swift"], "rules": [
            {"id": "scoped", "pattern": r"Prim\.", "paths": ["Sources/UI/"]},
            {"id": "plain", "pattern": r"Color\(\s*red\s*:"}]}), encoding="utf-8")
        rc, out = run_doc("```swift\nlet a = Prim.accent40\n```\n")
        case("置き場つきは当てない", rc, 0)
        if "当てていません" not in out:
            bad.append("置き場つきを当てていないことを報せていません")

    if bad:
        for b in bad:
            print(b)
        print(f"NG: 自己検査が {len(bad)} 件落ちました。**この道具が空振りしています。**")
        return 1
    print("OK: 自己検査 8 件とも期待どおりでした")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="文書のコード例が禁止に当たっていないか")
    ap.add_argument("--docs", type=Path, help="md の置き場（ディレクトリかファイル）")
    ap.add_argument("--rules", type=Path, help="rules.json")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if not a.docs or not a.rules:
        print("--docs と --rules の両方を指定してください")
        return 2
    return run(a.docs, a.rules)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # mutation-ok: 例外の帰り道。中からは通せない
        print(f"例外で止まりました: {e}")
        sys.exit(2)
