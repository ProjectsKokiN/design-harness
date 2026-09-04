#!/usr/bin/env python3
"""決定の取り消しを機械で扱う（2026-09-04 新設・#19）。

## 実害（aub-familywalk・2026-09-03）

**1日で決定が2回ひっくり返り、どちらも実装を変えてから戻す手戻り**になりました。

| 時刻順 | ユーザーの言葉 | 実装 |
|---|---|---|
| 先 | 「セーフエリアのところは透明に。**何も塗りの色をつけないでください**」 | 帯を内側へずらし、コメントに「**安全領域には何も塗りません**」と書いた |
| 後 | 「セーフエリアのところですが、今回のアプリでは**白塗り**に」 | 白で塗り、コメントを書き換えた |

**`DECISIONS.md` は追記式なので、前の決定（透明）がそのまま残り、生きている
ように読めます。** 実装コメントにも「何も塗りません」と書いてあったので、
**次に読む人（AI）は矛盾した2つの正を見ます。**

## 書き方

    ## 2026-09-03（2回目）安全領域は白で塗る

    **supersedes: 2026-09-03（1回目）安全領域には何も塗らない**

**取り消しは消しません**（経緯が要る）。ただし**取り消し済みと機械で分かる**
ようにします。

## 落とすもの

| | |
|---|---|
| `supersedes` が指す見出しが実在しない | 落とす（綴り違い・消してしまった） |
| **取り消された決定の見出しを、実装が引用している** | 落とす（**今回まさに起きた形**） |
| 同じ見出しが2つある | 落とす（どちらを取り消したか決められない） |
| 自分自身を取り消している | 落とす |

## 捕まえないもの

- 決定の**中身が正しいか**
- 取り消しを**書き忘れた**こと。書いていない取り消しは機械には見えません
  （**だから「決定が変わったら supersedes を書く」を手順に置きます**）
- 確かめた方法: --self-test（4つそれぞれが仕込みで落ちること）
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

#: 決定の見出しは `## ` だけ。`### ` は節の中の小見出し（「決めたこと」など）で、
#: 同じ言葉が何度も出るのが普通（aub の実測: 53件の中に2つあった）
HEAD_RX = re.compile(r"^##\s+(?!#)(.+?)\s*$", re.M)
SUPERSEDES_RX = re.compile(r"supersedes:\s*(.+?)\s*(?:\*\*)?\s*$", re.M | re.I)

#: 取り消された見出しから、実装が引用していないか探すときの最小の長さ
MIN_QUOTE = 6


def parse(text):
    """見出しと、その節の supersedes を返す。"""
    heads = [(m.group(1).strip(), m.start()) for m in HEAD_RX.finditer(text)]
    out = []
    for i, (name, pos) in enumerate(heads):
        end = heads[i + 1][1] if i + 1 < len(heads) else len(text)
        body = text[pos:end]
        sup = [s.strip().strip("*") for s in SUPERSEDES_RX.findall(body)]
        out.append({"name": name, "supersedes": sup, "body": body})
    return out


def quoted_in(impl_dirs, phrase, suffixes):
    """取り消された決定の言い回しを、実装が引用していないか。

    **語尾は変わります。** aub の実害では、決定の見出しが
    「安全領域には**何も塗らない**」で、実装のコメントが
    「安全領域には**何も塗りません**」でした。まるごと一致では当たりません。

    そこで2段で見ます。

    | | 出し方 |
    |---|---|
    | まるごと一致 | **引用しています**（確か） |
    | **前寄りの部分**が一致 | 言い回しが違うが**同じことを指していませんか**（疑い） |

    見るのは**コメント行だけ**です。文字列そのものは実装の値なので数えません。
    """
    hits = []
    core = phrase.split("）")[-1].strip() or phrase
    if len(core) < MIN_QUOTE:
        return hits
    head = core[:max(MIN_QUOTE, len(core) * 2 // 3)]
    for d in impl_dirs:
        if not d.exists():
            continue
        for f in sorted(d.rglob("*")):
            if not f.is_file() or f.suffix not in suffixes:
                continue
            text = f.read_text(encoding="utf-8", errors="ignore")
            for i, line in enumerate(text.splitlines(), 1):
                s = line.strip()
                if not (s.startswith("//") or s.startswith("#")
                        or s.startswith("*") or s.startswith("///")):
                    continue
                if core in line:
                    hits.append((f, i, s[:80], True))
                elif head in line:
                    hits.append((f, i, s[:80], False))
    return hits


def main(argv=None):
    ap = argparse.ArgumentParser(description="決定の取り消しを見る")
    ap.add_argument("--decisions", type=Path, default=Path("DECISIONS.md"))
    ap.add_argument("--impl", nargs="*", default=["lib"],
                    help="実装の置き場（取り消された文言の引用を探す）")
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--suffixes", nargs="*", default=[".dart", ".ts", ".tsx", ".py"])
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    if not args.decisions.exists():
        print(f"決定の記録がありません: {args.decisions}\n"
              f"  **決定がどこにも残っていない状態です。**", file=sys.stderr)
        return 2
    text = args.decisions.read_text(encoding="utf-8")
    items = parse(text)
    if not items:
        print(f"決定が1つも読めません: {args.decisions}\n"
              f"  決定の見出しは `## ` で書いてください。"
              f"**0件は「矛盾なし」ではありません。**", file=sys.stderr)
        return 2

    names = [i["name"] for i in items]
    errs = []
    dup = {n for n in names if names.count(n) > 1}
    for n in sorted(dup):
        errs.append(f"  同じ見出しが2つ以上あります: 「{n}」\n"
                    f"    **どちらを取り消したのか決められません。**")

    dead = set()
    for it in items:
        for s in it["supersedes"]:
            if s == it["name"]:
                errs.append(f"  「{it['name']}」が**自分自身を取り消しています**。")
                continue
            if s not in names:
                errs.append(f"  「{it['name']}」の supersedes が指す決定が"
                            f"ありません: 「{s}」\n"
                            f"    綴り違いか、消してしまった可能性があります。")
                continue
            dead.add(s)

    base = args.root.resolve()
    impl = [base / p for p in args.impl]
    for s in sorted(dead):
        for f, line, snippet, exact in quoted_in(impl, s, tuple(args.suffixes)):
            how = ("**取り消された決定を実装が引用しています**" if exact
                   else "取り消された決定と**同じことを言っていませんか**"
                        "（語尾だけ違います）")
            errs.append(f"  {how}: {f.relative_to(base)}:{line}\n"
                        f"    「{s}」は取り消されました。\n"
                        f"    {snippet}\n"
                        f"    **次に読む人は矛盾した2つの正を見ます。**")

    if errs:
        print(f"決定の記録に問題があります（決定 {len(items)} 件 / "
              f"取り消し済み {len(dead)} 件）:", file=sys.stderr)
        print("\n".join(errs), file=sys.stderr)
        return 1
    print(f"決定の記録: {len(items)} 件（うち取り消し済み {len(dead)} 件）。"
          f"矛盾はありません。")
    return 0


def self_test():
    import contextlib
    import io
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "lib").mkdir()
        dec = root / "DECISIONS.md"
        src = root / "lib" / "a.dart"

        def run(md, code="// ふつうのコメント\n"):
            dec.write_text(md, encoding="utf-8")
            src.write_text(code, encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = main(["--decisions", str(dec), "--root", str(root),
                           "--impl", "lib"])
            return rc, buf.getvalue()

        OKMD = ("## 2026-09-03（1回目）安全領域には何も塗らない\n\n本文\n\n"
                "## 2026-09-03（2回目）安全領域は白で塗る\n\n"
                "**supersedes: 2026-09-03（1回目）安全領域には何も塗らない**\n")
        rc, out = run(OKMD)
        if rc != 0 or "取り消し済み 1 件" not in out:
            print(f"self-test NG: 正しい取り消しで落ちた（{rc}）\n   {out[:300]}")
            ok = False

        # **取り消された決定を実装が引用している**（今回まさに起きた形）
        # **語尾が違っても捕まえる**（aub の実害そのもの）
        rc, out = run(OKMD, "// **安全領域には何も塗りません**\n")
        if rc != 1 or "同じことを言っていませんか" not in out:
            print(f"self-test NG: 語尾の違う引用を見逃した（{rc}）\n   {out[:300]}")
            ok = False
        # まるごと一致は「引用しています」と言い切る
        rc, out = run(OKMD, "// 安全領域には何も塗らない\n")
        if rc != 1 or "実装が引用しています" not in out:
            print(f"self-test NG: まるごと一致を見逃した（{rc}）"); ok = False

        # supersedes が実在しない見出しを指す
        rc, out = run(OKMD.replace("2026-09-03（1回目）安全領域には何も塗らない**",
                                   "2026-09-03（1回目）安全領域には何もぬらない**"))
        if rc != 1 or "指す決定がありません" not in out:
            print(f"self-test NG: 綴り違いの supersedes を通した（{rc}）"); ok = False

        # `###` の小見出しは決定として数えない（同じ言葉が何度も出るのが普通）
        rc, out = run(OKMD + "\n### 決めたこと\n\nx\n\n### 決めたこと\n\ny\n")
        if rc != 0:
            print(f"self-test NG: 小見出しを決定として数えた（{rc}）"); ok = False

        # 同じ見出しが2つ
        rc, out = run("## A\n\n本文\n\n## A\n\n本文\n")
        if rc != 1 or "同じ見出しが2つ" not in out:
            print(f"self-test NG: 同じ見出しを通した（{rc}）"); ok = False

        # 自分自身を取り消す
        rc, out = run("## A\n\n**supersedes: A**\n")
        if rc != 1 or "自分自身を取り消しています" not in out:
            print(f"self-test NG: 自己参照を通した（{rc}）"); ok = False

        # コメント以外の行は引用と数えない（**文字列そのものは実装の値**）
        rc, out = run(OKMD, "const s = '安全領域には何も塗りません';\n")
        if rc != 0:
            print(f"self-test NG: コメントでない行を引用と数えた（{rc}）"); ok = False

        # 決定が1つも読めなければ落ちる
        rc, out = run("見出しのない散文だけ\n")
        if rc != 2:
            print(f"self-test NG: 決定0件で通した（{rc}）"); ok = False
    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
