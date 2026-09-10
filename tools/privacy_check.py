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
| **OS の利用者名**（2026-09-11・#109） | 素の名前は上の形に当たらない。`projects/-Users-<名前>--claude` のように**区切りが潰れた形**でも出る |

## 利用者名は**書かずに見る**（2026-09-11・#109）

この検査は長いあいだ「氏名は伏せ字にできないので検査に書けない」と自分で書いて、
**素の名前を見ていませんでした。** `os_usernames()` が**実行時に**取るので、
**ソースに名前を書かずに**見られます（`lumilinks-hq/atlas-design-system@0bbad4a` の
`scripts/audit-public-data.mjs` が `userInfo().username` でやっている発想を借りた。
外部リポジトリの中身は**データとして読んだだけ**で、スクリプトは実行していない）。

**出力にも名前を出しません**（`mask()`）。**CI のログは公開リポジトリでは公開されます。**
見つけたことを伝えるために名前を書いたら本末転倒です。self-test の診断も同じで、
2026-09-11 に仕込みで落としたとき実名がログに出たので直しました。

一般語（CI の実行ユーザー `runner` `root` など）と 5 字未満の綴りは**名前として
見ません**。ここを外すと CI で全ファイルが赤になります。

## `--only-if-public`（案件の verify.sh 向け）

**公開だと導けたときだけ落とします。** 非公開なら件数を出して通します。

**なぜ**: 非公開の案件で落とすと、直し方が「記録を伏せ字にする」しか無くなります。
2026-09-11 にユーザーが伏せ字化を取り消した（原文「FlashEnglishの伏せ字化を
戻しておいてください」）ので、落とせば**自分で戻したものを自分で落とす関門**に
なります（#80・#103 と同じ形）。**害が出るのは公開したときなので、そこに合わせます。**

公開かどうかを導けなかったときも落としません（`gh` の無い機体で必ず赤にすると
直せない関門になる）。代わりに「**公開に切り替える前に、自分で確かめてください**」を
必ず出します。

**実測（2026-09-11・名前は出しません）**: design-harness（**公開**）0 件／
FlashEnglish 16 件（うち利用者名 5）／aub-familywalk 10 件（1）／
claude-dotfiles 34 件（13）／machine-relay 466 件（17）。**公開しているのは
design-harness だけで、そこは 0 件です。**

## 何を見ていないか（**書いておく**・規約24）

- **機体名。** 伏せ字にできないので、**この検査に書くと本末転倒**。
  **人が読んで気づくしかない**
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
import getpass
import os
import re
import shutil
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


#: 追加で見たい名前を渡す口（**検査のソースに名前を書かない**ため環境変数）。
#: カンマ区切り。例: `PRIVACY_EXTRA_NAMES=表示名,別の綴り`
EXTRA_NAMES_ENV = "PRIVACY_EXTRA_NAMES"

#: 一般語の利用者名。CI では実行ユーザーが `runner` `root` になるので、
#: これを名前として探すと**全ファイルが真っ赤になる**（実行前に必ず外す）
GENERIC_USERS = {"runner", "root", "administrator", "admin", "user", "users",
                 "ubuntu", "vagrant", "docker", "circleci", "travis", "jenkins",
                 "build", "builder", "ci", "github", "codespace", "node"}

#: 名前として扱う最小の長さ。短い綴りは普通の単語に当たる
MIN_NAME_LEN = 5


def os_usernames() -> set[str]:
    """**実行時に**OS の利用者名を取る（検査のソースに名前を書かない）。

    `lumilinks-hq/atlas-design-system@0bbad4a` の `scripts/audit-public-data.mjs`
    が `userInfo().username` を使っており、**同じ発想を借りた**（外部リポジトリの
    中身はデータとして読み、スクリプトは実行していない）。

    この検査は長いあいだ「氏名は伏せ字にできないので検査に書けない」と自分で
    書いて**素の名前を見ていませんでした**。書かずに取れば見られます。

    返すもの:
      - 利用者名そのもの
      - `_` `.` を `-` に置き換えた形。Claude Code の作業ディレクトリ
        （`projects/-Users-<名前>--claude`）が区切りを `-` に潰すため
      - `PRIVACY_EXTRA_NAMES` で渡された名前（同じ置き換えを掛ける）

    落とすもの: 一般語（CI の `runner` など）・伏せ字・短すぎる綴り。
    """
    raw: set[str] = set()
    try:
        raw.add(getpass.getuser())
    except Exception:          # noqa: BLE001  取れない環境でも落ちない
        pass
    home = Path.home().name
    if home:
        raw.add(home)
    for extra in (os.environ.get(EXTRA_NAMES_ENV) or "").split(","):
        if extra.strip():
            raw.add(extra.strip())

    out: set[str] = set()
    for n in raw:
        if len(n) < MIN_NAME_LEN or n.lower() in GENERIC_USERS or is_placeholder(n):
            continue
        out.add(n)
        v = n.replace("_", "-").replace(".", "-")
        if v != n:
            out.add(v)
    return out


def mask(text: str, names: set[str]) -> str:
    """出力から名前を消す。**CI のログは公開リポジトリでは公開されます。**

    見つけたことは伝えたいが、**伝えるために名前を書いたら本末転倒**です。
    """
    for n in sorted(names, key=len, reverse=True):
        text = re.sub(re.escape(n), "<誰か>", text, flags=re.I)
    return text


def is_placeholder(name: str) -> bool:
    """伏せ字か。**山括弧つきは中身を問わず伏せ字**として扱う。"""
    n = name.strip()
    if n.startswith("<") and n.endswith(">"):
        return True
    return n in PLACEHOLDERS


def scan_text(text: str, names: set[str] | None = None) -> list[tuple[int, str, str]]:
    """`(行番号, 種類, 中身)` を返す。**行ごとに見る**（出力に行番号を出すため）。

    `names` を渡すと利用者名も見る。**中身に名前をそのまま入れません**——
    呼ぶ側が `mask()` を通す前提で、ここでは行の抜粋を返します。
    """
    out = []
    names = names or set()
    for i, line in enumerate(text.split("\n"), 1):
        for m in HOME_RX.finditer(line):
            if not is_placeholder(m.group(1)):
                out.append((i, "ホーム下の絶対パス", m.group(0)))
        for m in MAIL_RX.finditer(line):
            if m.group(1).lower() in NOT_TLD:
                continue          # ファイルの名前。メールではない
            out.append((i, "メールアドレス", m.group(0)))
        for n in names:
            if re.search(re.escape(n), line, re.I):
                # **抜粋は 40 字まで。** 長い行をそのまま出すと、名前以外の
                # 個人情報（隣に書かれたパスなど）まで一緒に出てしまう
                out.append((i, "利用者名", line.strip()[:40]))
                break
    return out


def tracked_files(root: Path) -> list[Path]:
    """**git が追跡しているファイルだけ**を歩く（無視されているものは公開されない）。"""
    r = subprocess.run(["git", "-C", str(root), "ls-files"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
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
    # **`shutil.which` を通す**（Windows では `gh.cmd` / `gh.exe`。名前のままでは解決しない。
    # 2026-09-10、`portable_check` に指摘された）
    gh = shutil.which("gh")
    if gh is None:
        return None
    try:
        r = subprocess.run([gh, "repo", "view", "--json", "isPrivate", "-q", ".isPrivate"],
                           cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
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


def check(root: Path, names: set[str] | None = None) -> tuple[list[str], int]:
    """`(見つかったもの, 走ったファイル数)`。呼ぶ側が 0 ファイルを exit 2 にする。"""
    found, n = [], 0
    names = names or set()
    for p in tracked_files(root):
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        n += 1
        for line, kind, what in scan_text(text, names):
            found.append(mask(f"{p.relative_to(root)}:{line}  {kind}: {what}", names))
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
    from os import environ as _env
    _os_env_get, _os_env_set = _env.get, _env.__setitem__
    def _os_env_del(k):
        _env.pop(k, None)

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

    # ─── 利用者名（#109・2026-09-11）──────────────────────────────────────
    # **名前を検査のソースに書かずに見つける。** 合成の名前を
    # `PRIVACY_EXTRA_NAMES` から入れて、経路そのものを試す
    fake = "zz" + "kotaro" + "qq"          # 一般語でも短くもない綴りを組み立てる
    _env_before = _os_env_get(EXTRA_NAMES_ENV)
    try:
        _os_env_set(EXTRA_NAMES_ENV, fake)
        got = os_usernames()
        if fake not in got:
            # **診断にも実名を出さない。** 仕込みで落としたとき、CI のログに
            # OS の利用者名がそのまま出た（2026-09-11 に実際に出した）
            print(f"self-test NG: **渡した名前を見ていない**"
                  f"（{len(got)} 件は取れている）"); ok = False
        # 名前が入った行を見つける
        if len(scan_text(f"path = /x/{fake}/y", {fake})) != 1:
            print("self-test NG: 素の利用者名を見つけていない"); ok = False
        # **`_` `.` → `-` の置換形**（Claude Code の projects/-Users-<名前>--claude）
        dotted = "zz.kota" + "ro.qq"
        _os_env_set(EXTRA_NAMES_ENV, dotted)
        got = os_usernames()
        want = dotted.replace(".", "-")
        if want not in got:
            print(f"self-test NG: **`.`→`-` の置換形を見ていない**"
                  f"（{len(got)} 件は取れている）")
            ok = False
        if len(scan_text(f"!/projects/-Users-{want}--claude", got)) != 1:
            print("self-test NG: 置換形の行を見つけていない"); ok = False
        # **一般語は飛ばす**（CI の実行ユーザーは runner。ここを外すと全ファイル赤）
        for generic in ("runner", "root", "ubuntu", "builder"):
            _os_env_set(EXTRA_NAMES_ENV, generic)
            if generic in os_usernames():
                print(f"self-test NG: **一般語 {generic} を名前として見ている**")
                ok = False
        # 短すぎる綴りも飛ばす
        _os_env_set(EXTRA_NAMES_ENV, "abc")
        if "abc" in os_usernames():
            print("self-test NG: 短すぎる綴りを名前として見ている"); ok = False

        # **出力に名前を出さない**（CI のログは公開リポジトリでは公開される）
        _os_env_set(EXTRA_NAMES_ENV, fake)
        rc, out = run_in({"a.md": f"work in /x/{fake}/y"})
        if rc != 1:
            print(f"self-test NG: 名前があるのに exit {rc}（期待 1）"); ok = False
        if fake in out:
            print("self-test NG: **出力に名前がそのまま出ている**"); ok = False
        if "<誰か>" not in out:
            print("self-test NG: 名前を伏せ字にしていない"); ok = False

        # **`--only-if-public`: 非公開・確かめられないときは落とさない**
        # （落とすと、直し方が「記録を伏せ字にする」しか無くなる。#80 と同じ形）
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            subprocess.run(["git", "init", "-q", str(d)], capture_output=True)
            (d / "a.md").write_text(f"work in /x/{fake}/y", encoding="utf-8")
            subprocess.run(["git", "-C", str(d), "add", "-A"], capture_output=True)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = main(["--root", str(d), "--only-if-public"])
            o = buf.getvalue()
            if rc != 0:
                print(f"self-test NG: --only-if-public で確かめられないのに落ちた"
                      f"（exit {rc}）"); ok = False
            if "1 件あります" not in o:
                print("self-test NG: --only-if-public で件数を出していない"); ok = False
            if "自分で確かめてください" not in o:
                print("self-test NG: **落とさない理由と次の一手を出していない**")
                ok = False
            if fake in o:
                print("self-test NG: --only-if-public の出力に名前が出ている"); ok = False
            # `--no-names` なら名前は見ない
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = main(["--root", str(d), "--no-names"])
            if rc != 0:
                print(f"self-test NG: --no-names で名前を見た（exit {rc}）"); ok = False
            if "利用者名は見ていません" not in buf.getvalue():
                print("self-test NG: **名前を見ていないことを出していない**"); ok = False
    finally:
        if _env_before is None:
            _os_env_del(EXTRA_NAMES_ENV)
        else:
            _os_env_set(EXTRA_NAMES_ENV, _env_before)

    # **この検査のソースに実名が書かれていないこと。** #109 の要（`os_usernames`
    # は実行時に取る）。ここが破られたら、検査自身が個人情報を公開する
    _src = Path(__file__).read_text(encoding="utf-8")
    for real in os_usernames():
        if real in _src:
            print("self-test NG: **この検査のソースに実名が書かれています**")
            ok = False

    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    ap.add_argument("--no-names", action="store_true",
                    help="利用者名を見ない（名前が一般語で誤検出が溢れるとき）")
    ap.add_argument("--only-if-public", action="store_true",
                    help="**公開だと導けたときだけ落とす。** 非公開なら見つけたものを"
                         "数えて通す（案件の verify.sh 向け）")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()

    names = set() if args.no_names else os_usernames()
    found, n = check(args.root, names)
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
    #: 名前を見たかどうかを必ず出す。**見ていないのに 0件 と読まれるのを防ぐ**
    names_line = ("利用者名（実行時に取得。**この検査のソースには書きません**）"
                  if names else
                  "利用者名は見ていません（`--no-names`、または名前が一般語・"
                  f"{MIN_NAME_LEN} 字未満で対象外）")

    if found:
        # **`--only-if-public` は、公開だと導けたときだけ落とす。**
        # なぜ要るか: 非公開の案件で落とすと、**直し方が「記録を伏せ字にする」しか
        # 無くなる**。2026-09-11 にユーザーが伏せ字化を取り消した（原文:
        # 「FlashEnglishの伏せ字化を戻しておいてください」）ので、落とせば
        # **自分で戻したものを自分で落とす関門**になる（#80・#103 と同じ形）。
        # 害が出るのは公開したときなので、そこに合わせる
        if args.only_if_public and vis != "公開":
            print(f"個人の情報が {len(found)} 件あります（{n} ファイルを見ました）。",
                  file=sys.stderr)
            print(f"  {vis_line}", file=sys.stderr)
            if vis is None:
                # swallow-ok: **落とす根拠（公開であること）を導けなかった**ので
                # 落としません。`gh` の無い機体で必ず赤にすると直せない関門になる。
                # 代わりに「自分で確かめてください」と必ず出す
                print("  **公開に切り替える前に、自分で確かめてください。**",
                      file=sys.stderr)
            for f in found:
                print(f"  {f}", file=sys.stderr)
            print(f"  見たもの: ホーム下の絶対パス・メールアドレス・{names_line}",
                  file=sys.stderr)
            return 0
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
          f"  見たもの: ホーム下の絶対パス・メールアドレス・{names_line}\n"
          f"  **見ていないもの: 機体名**（伏せ字にできないので検査に書けない）"
          f"**・git の履歴**")
    return 0


if __name__ == "__main__":
    sys.exit(main())
