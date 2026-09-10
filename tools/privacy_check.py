#!/usr/bin/env python3
"""**公開してよいものだけが入っているか**を見る（2026-09-07 新設）。

## なぜ要るか

**2026-09-06、公開リポジトリに個人の情報が入りました。** 気づいたのは翌日で、
入れたのは検査そのものではなく**手で書いた文書**でした。

    ホーム下の絶対パス   407 箇所（1ファイルで 310）
    メールアドレス        2 種
    氏名・機体名          43 箇所

**既にある道具はどれも当たりませんでした。**

| 道具 | 対象 | なぜ当たらないか |
|---|---|---|
| `generated_check` | **印を持つ生成物だけ** | 手で書いた文書は歩かない |
| `portable_check` | Windows で落ちる書き方 | 見ているのは文字コードとパス区切り |

**手で書く文書に当たる入り口が無かった**、というのが穴でした。

## 何を見るか

| 見るもの | なぜ |
|---|---|
| **ホーム下の絶対パス**（`/Users/<誰か>/` `/home/<誰か>/` `C:\\Users\\<誰か>\\`） | ユーザー名が出る。**機体でも違うので移植性の問題でもある** |
| **メールアドレス** | 個人の連絡先 |

## 何を見ていないか（**書いておく**・規約24）

- **氏名と機体名。** 伏せ字にできないので、**この検査に書くと本末転倒**（検査自身が
  個人情報を公開することになる）。**人が読んで気づくしかない**
- **git の履歴。** 見るのは作業ツリーだけ。**履歴に入ったものはこの検査では消えない**
- **画像の中の文字**・バイナリ

## 通すもの

伏せ字（`<誰か>` `<name>` `someone` `user` `runner` など）は通します。
**検出のための試験データが落ちてしまう**ためです。

## 公開かどうかは**導きます**（2026-09-10 に直した）

**この道具は「**このリポジトリは公開です**」と無条件で出していました。**
`isPrivate` も `visibility` も見ずに、確かめていないことを断定していました。

**実害（2026-09-10）**: FlashEnglish（**非公開**）の作業ツリーに当てた出力を、
読んだ側（AI）がそのまま事実として受け取り、**「公開リポジトリに個人情報が 6 件」と
ユーザーへ誤って報告しました。** そのうえ間違った前提で共有ファイル 3 本を書き換えて
push しました。**嘘の緊急性を作るのが、この形のいちばん重い害です。**

いまは `gh repo view --json isPrivate` から導きます。**取れないときは言いません**
（「公開かどうかは確かめられませんでした」と出す）。**取れないのに断定するのが最悪です。**

## 0件の扱い

**ここは 0件が正常です。** そのぶん「見ていない」と区別が付きません。
**走ったファイル数を必ず出し、0ファイルなら exit 2**（走査が空振りしたことを緑にしない）。

    python3 tools/privacy_check.py
    python3 tools/privacy_check.py --self-test
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

#: ホーム下の絶対パス。**2つ目の区切りまで**を見て、そこがユーザー名
HOME_RX = re.compile(r"(?:/Users/|/home/|[A-Za-z]:\\{1,2}Users\\{1,2})([A-Za-z0-9][A-Za-z0-9._-]*)")
#: メールアドレス。**末尾がファイルの拡張子なら通す**——`Icon-20@2x.png` のような
#: 資産の名前がメールに見えるため（2026-09-07 に実際に誤検出した）
MAIL_RX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.([A-Za-z]{2,})")
NOT_TLD = {"png", "jpg", "jpeg", "gif", "webp", "pdf", "svg", "ttf", "otf",
           "json", "md", "py", "js", "mjs", "dart", "sh", "ps1", "yml", "yaml",
           "txt", "html", "css", "xml", "plist", "lock", "kts", "gradle"}

#: 伏せ字。**これらは人の名前ではないので通す**
PLACEHOLDERS = {
    "<誰か>", "<name>", "<user>", "<ユーザー>", "someone", "user", "username",
    "runner", "you", "me", "example", "<誰>", "<n>", "USER", "$USER", "%USERNAME%",
    "dareka", "somebody", "anyone", "test", "tester", "dummy", "foo", "bar",
    "someuser", "otheruser", "other", "sampleuser", "myname",
}
#: 走らない場所
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".dart_tool", "build", "dist"}
#: 走らない拡張子（バイナリ）
SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".ttf", ".otf",
            ".woff", ".woff2", ".zip", ".ico", ".mp4", ".mov"}


def is_placeholder(name: str) -> bool:
    """伏せ字か。**山括弧つきは中身を問わず伏せ字**として扱う。"""
    n = name.strip()
    if n.startswith("<") and n.endswith(">"):
        return True
    return n in PLACEHOLDERS


def scan_text(text: str) -> list[tuple[int, str, str]]:
    """`(行番号, 種類, 中身)` を返す。**行ごとに見る**（出力に行番号を出すため）。"""
    out = []
    for i, line in enumerate(text.split("\n"), 1):
        for m in HOME_RX.finditer(line):
            if not is_placeholder(m.group(1)):
                out.append((i, "ホーム下の絶対パス", m.group(0)))
        for m in MAIL_RX.finditer(line):
            if m.group(1).lower() in NOT_TLD:
                continue          # ファイルの名前。メールではない
            out.append((i, "メールアドレス", m.group(0)))
    return out


def tracked_files(root: Path) -> list[Path]:
    """**git が追跡しているファイルだけ**を歩く（無視されているものは公開されない）。"""
    r = subprocess.run(["git", "-C", str(root), "ls-files"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return sorted(p for p in root.rglob("*") if p.is_file())
    out = []
    for rel in r.stdout.splitlines():
        p = root / rel
        if not p.is_file():
            continue
        if set(p.parts) & SKIP_DIRS or p.suffix.lower() in SKIP_EXT:
            continue
        out.append(p)
    return out


def visibility(root: Path) -> str | None:
    """公開かどうかを**導く**。分からなければ `None`（**断定しない**）。

    `gh` が無い・認証が無い・remote が GitHub ではない、のどれでも `None` です。
    **`None` を「公開」に丸めません**——2026-09-10 に、確かめていない断定が
    嘘の緊急性を作りました（docstring の「公開かどうかは導きます」を参照）。
    """
    try:
        r = subprocess.run(["gh", "repo", "view", "--json", "isPrivate", "-q", ".isPrivate"],
                           cwd=str(root), capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        # **`gh` が入っていない機体・CI で落ちてはいけない**（この検査の本体は
        # 個人情報の走査で、公開かどうかは添え物）。2026-09-10 に PATH を外して踏んだ
        return None
    if r.returncode != 0:
        return None
    out = r.stdout.strip()
    if out == "true":
        return "非公開"
    if out == "false":
        return "公開"
    return None


def check(root: Path) -> tuple[list[str], int]:
    """`(見つかったもの, 走ったファイル数)`。呼ぶ側が 0 ファイルを exit 2 にする。"""
    found, n = [], 0
    for p in tracked_files(root):
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        n += 1
        for line, kind, what in scan_text(text):
            found.append(f"{p.relative_to(root)}:{line}  {kind}: {what}")
    return found, n


def self_test() -> int:
    ok = True

    def check_case(name, text, want):
        nonlocal ok
        got = len(scan_text(text))
        if got != want:
            print(f"self-test NG: {name} → {got} 件（期待 {want}）")
            ok = False

    # **わざと落とすための例は、組み立てて作る。**
    # 実名らしき文字列をそのまま書くと、**この検査自身がこのファイルで落ちます**
    # （2026-09-07 に実際に踏んだ。伏せ字にすると今度は落ちなくなるので、組み立てる）
    u = "real" + "name"
    check_case("mac のホーム", f'見よ /Users/{u}/dev/x.js', 1)
    check_case("linux のホーム", f'path=/home/{u}/x', 1)
    check_case("windows のホーム", f'C:\\Users\\{u.title()}\\x', 1)
    # メールも同じ理由で組み立てる（`@` を含む文字列をそのまま書くと自分で落ちる）
    mail = "a.b" + "@" + "example.co.jp"
    check_case("メールアドレス", f'connect {mail} です', 1)
    check_case("1行に2件", f'/Users/{u}/a と /home/{u}2/b', 2)
    # 通すもの（**伏せ字**。ここが落ちると、検出のための試験データが書けなくなる）
    check_case("伏せ字（山括弧）", '/Users/<誰か>/dev/x.js', 0)
    check_case("伏せ字（someone）", '/Users/someone/dev/x.js', 0)
    check_case("伏せ字（runner・CI）", '/home/runner/work/x', 0)
    check_case("ホームの記法", '~/dev/design-harness/tools', 0)
    check_case("相対パス", 'tools/privacy_check.py:12', 0)
    # **2026-09-07 に実際に誤検出した2件**。どちらも「見つけるための道具」の中にあった
    check_case("資産の名前（メールに見える）", '_png(ios / "Icon-20@2x.png", 20, 20)', 0)
    check_case("regex のソース", r'HOME_ABS = re.compile(r"(/Users/[^/\"\s]+/|/home/[^/\"\s]+/)")', 0)
    check_case("伏せ字（dareka）", '{"a": "/Users/dareka/x"}', 0)
    # 伏せ字の判定そのもの
    for s, want in (("<誰か>", True), ("someone", True), ("runner", True),
                    (u, False), ("a." + u, False)):
        if is_placeholder(s) != want:
            print(f"self-test NG: is_placeholder({s!r}) が {not want}"); ok = False

    # ─── 通しで見る（**終了コードは main() が決めるので、そこまで測る**）───────
    # 変異試験が `return 1` / `return 2` を `return 0` に替えても self-test が
    # 通ってしまうと、**落とす帰り道が測られていない**ことになる
    import contextlib, io, subprocess, tempfile

    def run_in(files):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            subprocess.run(["git", "init", "-q", str(d)], capture_output=True)
            for name, body in files.items():
                (d / name).write_text(body, encoding="utf-8")
            if files:
                subprocess.run(["git", "-C", str(d), "add", "-A"], capture_output=True)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = main(["--root", str(d)])
            return rc, buf.getvalue()

    rc, out = run_in({"a.md": f"見よ /Users/{u}/dev/x.js"})
    if rc != 1 or "公開してはいけない" not in out:
        print(f"self-test NG: **実パスがあるのに exit {rc}**（期待 1）"); ok = False

    # ─── 公開かどうかを**断定しない**（2026-09-10 の実害）─────────────────
    # 一時ディレクトリは GitHub の remote を持たないので `visibility()` は None。
    # **None を「公開」に丸めると、この道具は嘘の緊急性を作る**
    if "公開かどうかは確かめられませんでした" not in out:
        print("self-test NG: **remote が無いのに公開かどうかを断定している**\n"
              f"   {out[:220]}"); ok = False
    for wrong in ("**このリポジトリは公開です。**", "このリポジトリは**非公開**です"):
        if wrong in out:
            print(f"self-test NG: **確かめていないのに {wrong!r} と言っている**"); ok = False
    # 導出そのもの: 一時ディレクトリでは None、この repo では 公開 / 非公開 のどちらか
    import tempfile as _tf
    with _tf.TemporaryDirectory() as _d:
        if visibility(Path(_d)) is not None:
            print("self-test NG: **remote の無い場所で公開かどうかを返した**"); ok = False
    _here = visibility(Path(__file__).resolve().parent.parent)
    if _here not in ("公開", "非公開", None):
        print(f"self-test NG: visibility() が {_here!r} を返した"); ok = False
    # **`gh` が無い機体・CI で落ちない**（2026-09-10 に PATH を外して踏んだ）
    import os as _os
    _path = _os.environ.get("PATH", "")
    _os.environ["PATH"] = "/nonexistent"
    try:
        if visibility(Path(__file__).resolve().parent.parent) is not None:
            print("self-test NG: gh が無いのに公開かどうかを返した"); ok = False
        # **`run_in` はここで呼べません**——PATH を外すと `git` も無くなり、
        # 測りたいもの（gh の不在）ではなく足場が壊れます（2026-09-10 に踏んだ）。
        # 走査が gh に依らないことは、上の「remote が無い」ケースが見ています
    finally:
        _os.environ["PATH"] = _path
    rc, out = run_in({"a.md": f"connect {mail}"})
    if rc != 1:
        print(f"self-test NG: **メールがあるのに exit {rc}**（期待 1）"); ok = False
    rc, out = run_in({"a.md": "/Users/<誰か>/x と ~/dev/y と Icon-20@2x.png"})
    if rc != 0 or "ファイルを見ました" not in out:
        print(f"self-test NG: 伏せ字だけなのに exit {rc}（期待 0）\n   {out[:200]}"); ok = False
    if "見ていないもの" not in out:
        print("self-test NG: **何を見ていないかを出していない**（規約24）"); ok = False
    # **0ファイルは「綺麗」ではなく「見ていない」**
    rc, out = run_in({})
    if rc != 2 or "見ていません" not in out:
        print(f"self-test NG: **1ファイルも読めないのに exit {rc}**（期待 2）"); ok = False
    # 走った数を必ず出す（出さないと 0件 が「見た結果」か「見なかった」か分からない）
    rc, out = run_in({"a.md": "何もない", "b.py": "x = 1\n"})
    if rc != 0 or "2 ファイルを見ました" not in out:
        print(f"self-test NG: 走ったファイル数を出していない（{rc}）\n   {out[:160]}"); ok = False
    # バイナリと走らない場所は数に入れない
    rc, out = run_in({"a.md": "ok", "b.png": "not really a png"})
    if "1 ファイルを見ました" not in out:
        print(f"self-test NG: 画像を数に入れている\n   {out[:160]}"); ok = False

    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()

    found, n = check(args.root)
    if n == 0:
        # **0件は「綺麗」ではなく「見ていない」。** 走査が空振りしたことを緑にしない
        print(f"{args.root} で1ファイルも読めませんでした。**見ていません。**\n"
              f"  git リポジトリですか（`git ls-files` が空）。--root を確かめてください",
              file=sys.stderr)
        return 2
    vis = visibility(args.root)
    #: 公開かどうかは**導いた結果だけ**を書く。分からないときは分からないと書く
    vis_line = {
        "公開": "**このリポジトリは公開です**（`gh repo view` で確かめました）。",
        "非公開": "このリポジトリは**非公開**です（`gh repo view` で確かめました）。"
                  "**公開に切り替える前に**直してください。",
        None: "**公開かどうかは確かめられませんでした**（`gh` が無い・認証が無い・"
              "remote が GitHub ではない）。**公開とも非公開とも言えません。**",
    }[vis]
    if found:
        print("公開してはいけないものが入っています。", file=sys.stderr)
        print(vis_line, file=sys.stderr)
        print("消しても **git の履歴には残ります。**", file=sys.stderr)
        for f in found:
            print(f"  {f}", file=sys.stderr)
        print(f"\n  伏せ字にしてください（`/Users/<誰か>/` の形）。"
              f"検出のための試験データも同じです。", file=sys.stderr)
        return 1
    print(f"見たかぎり公開してよいものだけです（{n} ファイルを見ました）。\n"
          f"  {vis_line}\n"
          f"  見たもの: ホーム下の絶対パス・メールアドレス\n"
          f"  **見ていないもの: 氏名・機体名**（伏せ字にできないので検査に書けない）"
          f"**・git の履歴**")
    return 0


if __name__ == "__main__":
    sys.exit(main())
