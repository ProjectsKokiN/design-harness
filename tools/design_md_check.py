#!/usr/bin/env python3
"""案件の DESIGN.md が、共通の憲法を「参照」しているかを見る（2026-08-29 新設）。

## なぜ要るか

共通の設計基準（原則・品質フロア・検証の段）を各案件の DESIGN.md に**手で写して**
いたため、共通側を直しても案件へ届きませんでした（flash-compose は156行・10.5KB の
うち案件固有は4節だけ）。検査エンジンを一本化したのと同じ問題です。

そこで共通部分を `design-harness/DESIGN.md` に集め、案件側は**参照＋案件固有だけ**に
します。submodule を pull すれば全案件が最新の憲法を読みます。

この検査は、その形が崩れていないことを機械で見ます。

## 見るもの

1. 案件の DESIGN.md が共通の憲法へのパスを書いているか（参照の配線）
2. 共通側が `required-sections` で宣言した見出しが、案件側に全部あるか（網羅）
3. 案件側の見出しが required-sections だけか（**許可リスト方式**。写しの再発防止で、
   ここが本体）。除外リスト方式だと、見出しを言い換えた写しが黙って通ります——
   flash-compose の「原則（5つ）」は、共通側の「設計原則」と文言が違うせいで
   すり抜けていました
4. `## スタック` の宣言が、共通側が定義したスタックのどれかか

## 捕まえないもの

- 案件固有の節の中身が正しいか（Phase の数字が実態と合っているか等）
- 参照先を書いたが実際には読まなかったセッション（これは規律の領域）
- 確かめた方法: --self-test（写しを仕込んで落ちること・見出し欠落で落ちること）

## 使い方（案件のルートで）

    python3 design/harness/tools/design_md_check.py \\
        [--project DESIGN.md] [--harness design/harness/DESIGN.md]
"""

import argparse
import re
import sys
from pathlib import Path

#: 共通側にあっても、案件側に同名の見出しがあってよいもの
ALLOW_DUP = ("案件側の DESIGN.md に必ず書くこと", "関係する正本")

#: 共通側が定義するスタックの取り出し（### スタック: flutter（iOS / Android アプリ））
STACK_RX = re.compile(r"^###\s*スタック\s*[:：]\s*([A-Za-z0-9_-]+)")

#: 共通側の見出しと文言は違うが、中身は共通の内容だった写し（実案件で観測したもの）。
#: flash-compose は「原則（5つ）」「禁止パターン（概要）」「主要トークン（抜粋）」を
#: 持っており、見出しの言い換えのせいで 3) の照合をすり抜けていた
EXTRA_BANNED = ("原則", "禁止パターン", "主要トークン")

#: 見出しの例外許可（理由を必ず書く。harness-ignore と同じ考え方）
ALLOW_RX = re.compile(r"<!--\s*design-md-allow\s*[:：]\s*(.+?)-->")

#: 共通の憲法への参照とみなすパス（案件は submodule の下に置く）
POINTER_RX = re.compile(r"harness/DESIGN\.md")


def strip_paren(text):
    """見出しの補足（…）を落として比較用に正規化する。"""
    return re.sub(r"[（(].*?[）)]", "", text).strip()


def headings(text, level="## "):
    """フェンス（```）の中を除いた見出しを返す。"""
    out, fence = [], False
    for i, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        if line.startswith(level) and not line.startswith(level + "#"):
            out.append((i, line[len(level):].strip()))
    return out


def fenced_block(text, tag):
    """```<tag> … ``` の中身の行を返す。"""
    out, inside = [], False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            if inside:
                break
            inside = line.strip()[3:].strip() == tag
            continue
        if inside:
            out.append(line.rstrip())
    return [l for l in out if l.strip()]


def main(argv=None):
    ap = argparse.ArgumentParser(description="案件の DESIGN.md が共通の憲法を参照しているか")
    ap.add_argument("--project", type=Path, default=Path("DESIGN.md"))
    ap.add_argument("--harness", type=Path, default=Path("design/harness/DESIGN.md"))
    ap.add_argument("--max-lines", type=int, default=80,
                    help="これを超えたら「写しが混ざっていないか」を注意する")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    if not args.harness.exists():
        print(f"共通の憲法がありません: {args.harness}\n"
              f"  submodule が入っていない可能性があります: "
              f"git submodule update --init", file=sys.stderr)
        return 2
    if not args.project.exists():
        print(f"案件の DESIGN.md がありません: {args.project}", file=sys.stderr)
        return 2

    common = args.harness.read_text(encoding="utf-8")
    proj = args.project.read_text(encoding="utf-8")

    problems, notes = [], []

    # 1) 参照の配線
    ref = str(args.harness)
    if ref not in proj and not POINTER_RX.search(proj):
        problems.append(
            f"共通の憲法への参照がありません。冒頭に次の1行を置いてください:\n"
            f"      **共通の憲法 `{ref}` を必ず読んでください。**")

    # 2) 網羅（共通側が宣言した見出しが案件側に全部あるか）
    required = [l.strip() for l in fenced_block(common, "required-sections")
                if l.strip().startswith("#")]
    if not required:
        problems.append(f"{args.harness} に required-sections の宣言がありません"
                        f"（この検査の分母が無い状態です）")
    have = {strip_paren(h) for _, h in headings(proj)}
    missing = [r for r in required if strip_paren(r.lstrip("# ")) not in have]
    if missing:
        problems.append("案件側に足りない見出し: " + " / ".join(missing))

    # 3) 写しの再発防止（許可リスト方式・ここが本体）
    required_norm = {strip_paren(r.lstrip("# ")) for r in required}
    known = {strip_paren(h) for _, h in headings(common)
             if strip_paren(h) not in {strip_paren(a) for a in ALLOW_DUP}}
    known |= {e for e in EXTRA_BANNED if e not in required_norm}
    lines = proj.splitlines()
    for ln, h in headings(proj):
        if strip_paren(h) in required_norm:
            continue
        prev = lines[ln - 2] if ln >= 2 else ""
        if ALLOW_RX.search(prev):
            notes.append(f"{args.project}:{ln}: 「{h}」を例外で許可しています"
                         f"（{ALLOW_RX.search(prev).group(1).strip()}）")
            continue
        if strip_paren(h) in known:
            problems.append(
                f"{args.project}:{ln}: 「{h}」は共通の憲法にある内容です。"
                f"案件側に写さないでください（共通側を直しても古いまま残ります）。"
                f"消して {ref} を参照してください")
        else:
            problems.append(
                f"{args.project}:{ln}: 「{h}」は案件側に置いてよい見出しの一覧に"
                f"ありません。共通の憲法にある内容なら消して参照してください。"
                f"案件固有なら `## この案件だけの決まり` の下に `###` で入れてください"
                f"（どうしても要るなら直前の行に "
                f"<!-- design-md-allow: 理由 --> を置いてください）")

    # 4) スタックの宣言
    stacks = [m.group(1) for m in
              (STACK_RX.match(l) for l in common.splitlines()) if m]
    m = re.search(r"^##\s*スタック.*$", proj, re.M)
    if m and stacks:
        tail = proj[m.end():m.end() + 400]
        declared = [s for s in stacks if re.search(rf"\b{re.escape(s)}\b", tail)]
        if not declared:
            problems.append(f"`## スタック` にスタックの宣言がありません。"
                            f"共通側が定義しているのは: {' / '.join(stacks)}")
        elif len(declared) > 1:
            notes.append(f"スタックを複数宣言しています: {declared}"
                         f"（品質フロアが両方適用されます）")

    n = len(proj.splitlines())
    if n > args.max_lines:
        notes.append(f"案件の DESIGN.md が {n} 行あります"
                     f"（目安 {args.max_lines} 行）。共通の内容が混ざっていないか"
                     f"見てください")

    print("DESIGN.md の参照体制:")
    for x in notes:
        print(f"  注意: {x}")
    if problems:
        print("\n共通の憲法との関係が崩れています:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print(f"  OK: 共通の憲法を参照し、案件固有の{len(required)}節がそろっています"
          f"（{n}行）。")
    return 0


def self_test():
    import tempfile
    ok = True
    common = (
        "# デザイン憲法（全案件共通）\n\n"
        "## 案件側の DESIGN.md に必ず書くこと\n\n"
        "```required-sections\n## 使うデザインシステム\n## スタック\n"
        "## 検証フェーズ\n```\n\n"
        "## 設計原則（6つ）\n本文\n\n"
        "## 品質フロア（すべての画面が満たす最低条件）\n\n"
        "### スタック: flutter\n- SafeArea\n\n"
        "### スタック: web\n- ズーム200%\n")
    good = ("# 案件 デザイン憲法\n\n"
            "**共通の憲法 `design/harness/DESIGN.md` を必ず読んでください。**\n\n"
            "## 使うデザインシステム\nfoo\n\n## スタック\nflutter\n\n"
            "## 検証フェーズ\nPhase 2\n")

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        h = base / "harness" / "DESIGN.md"
        h.parent.mkdir()
        h.write_text(common, encoding="utf-8")
        p = base / "DESIGN.md"

        def run(body):
            p.write_text(body, encoding="utf-8")
            return main(["--project", str(p), "--harness", str(h)])

        # そのままの形は通る
        if run(good) != 0:
            print("self-test NG: 正しい形なのに落ちた"); ok = False

        # 参照が無い
        if run(good.replace("**共通の憲法 `design/harness/DESIGN.md` "
                            "を必ず読んでください。**\n\n", "")) != 1:
            print("self-test NG: 参照が無いのに落ちなかった"); ok = False

        # 見出しが欠けている
        if run(good.replace("## 検証フェーズ\nPhase 2\n", "")) != 1:
            print("self-test NG: 見出しが欠けているのに落ちなかった"); ok = False

        # 共通の内容を写している（本体の検査）
        if run(good
               + "\n## 設計原則\n1. トークン外を使わない\n") != 1:
            print("self-test NG: 共通の内容を写しているのに落ちなかった"); ok = False
        if run(good
               + "\n## 品質フロア（この案件の最低条件）\n- SafeArea\n") != 1:
            print("self-test NG: 補足つきの写しを見逃した"); ok = False

        # 言い換えた写し（flash-compose の「原則（5つ）」で実際にすり抜けた形）
        if run(good + "\n## 原則（5つ）\n1. トークン外を使わない\n") != 1:
            print("self-test NG: 言い換えた写しを見逃した"); ok = False
        if run(good + "\n## 主要トークン（抜粋）\n| 色 | x |\n") != 1:
            print("self-test NG: トークン抜粋の写しを見逃した"); ok = False

        # 一覧に無い見出し（許可リスト方式の本体）
        if run(good + "\n## 画面の一覧\nA / B\n") != 1:
            print("self-test NG: 一覧に無い見出しを見逃した"); ok = False
        if run(good + "\n<!-- design-md-allow: 案件の索引 -->\n"
                      "## 画面の一覧\nA / B\n") != 0:
            print("self-test NG: 例外許可が効かなかった"); ok = False

        # スタックが宣言されていない
        if run(good
                   .replace("## スタック\nflutter", "## スタック\n未定")) != 1:
            print("self-test NG: スタック未宣言なのに落ちなかった"); ok = False

    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
