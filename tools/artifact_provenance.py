#!/usr/bin/env python3
"""**配った物の側から、どのコードで作ったかが分かるか**を見る。

## 実害（2026-09-07）

**iOS の配布物には何も残っていません。** `flutter build ipa` が出すのは
`Runner.ipa` で、**どのコミットから作ったかは名前のどこにもありません。**
配った TestFlight のビルドが手元のどの版なのか、**成果物の側からは辿れません。**

Android は両案件とも残しています。

    aub-familywalk   iichoshi-walk-<版>-<YYYY-MM-DD>-<SHA>.apk
    FlashEnglish     FlashEnglish-<flavor>-<YYYYMMDD>-<SHA>[-dirty].apk

**片側にしか無いので、共有の規約にできませんでした**（規約15 を取り下げた理由）。

## 名前の形を決めません。**素性が取れるかだけを見ます**

上の2つは形が違います（片方は版を入れ、もう片方は flavor と `-dirty` を入れる）。
**どちらも正しい**ので、**形をそろえろとは言いません。**

**見るのは1つだけ——名前から「このリポジトリに実在するコミット」が取り出せるか。**
これなら**両案件とも今のまま通り**、iOS だけが落ちます。**宣言せず、導出します。**

## `-dirty` について（FlashEnglish の知見）

汚れた木から作ると、**どの SHA も中身を指していません。** FlashEnglish は
`-dirty` を付けますが、**`git status` 全体で見ると `SESSION_LOG.md` を書いただけで
付いてしまい、ほぼ毎回付くので目印の意味を失います**（実測済み）。
**配布物の中身に入るものだけを数える**のが正しい形です。

## 終了コード

    0  素性が取れる（**どのコミットかを出す**）
    1  取れない（配布物はあるのに、名前にコミットが無い）
    2  **確かめられなかった**（配布物が1つも無い・リポジトリでない・git が無い）
"""
import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401

#: 配布物とみなす拡張子。**ここに無いものは数えません**
ARTIFACT_SUFFIXES = (".ipa", ".apk", ".aab", ".app.zip")
#: 名前の中のコミットらしき並び。git の短縮は既定 7 桁
SHA_RX = re.compile(r"(?<![0-9a-zA-Z])([0-9a-f]{7,40})(?![0-9a-zA-Z])")
DIRTY_RX = re.compile(r"(?<![0-9a-zA-Z])dirty(?![0-9a-zA-Z])")


def _git(args, cwd):
    exe = shutil.which("git")
    if not exe:
        return None
    try:
        r = subprocess.run([exe] + args, cwd=str(cwd), capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
    except OSError:
        return None
    return r.returncode, r.stdout.strip()


def resolve(token, root: Path):
    """`token` がこのリポジトリの実在するコミットなら、その完全な SHA を返す。"""
    r = _git(["rev-parse", "--verify", "--quiet", f"{token}^{{commit}}"], root)
    if r is None:
        return None
    rc, out = r
    return out if rc == 0 and out else None


def find_artifacts(paths, suffixes=ARTIFACT_SUFFIXES):
    """**中身を見ずに、名前だけで集めます。**"""
    out = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and f.name.endswith(suffixes):
                    out.append(f)
        elif p.is_file() and p.name.endswith(suffixes):
            out.append(p)
        elif p.is_file():
            out.append(p)          # 明示で渡されたものは拡張子を問わない
    return out


def check(paths, root: Path):
    """`(終了コード, 行の一覧)` を返す。"""
    if _git(["rev-parse", "--is-inside-work-tree"], root) is None:
        return 2, ["**git がありません。**素性を照合できないので落とします"]
    rc_git, inside = _git(["rev-parse", "--is-inside-work-tree"], root)
    if rc_git != 0 or inside != "true":
        return 2, [f"**git のリポジトリではありません**: {root}",
                   "  コミットの実在を確かめられません"]

    found = find_artifacts(paths)
    if not found:
        return 2, [f"**配布物が1つも見つかりません**: "
                   f"{', '.join(str(p) for p in paths)}",
                   "  **0件は「素性がある」ではなく「見ていない」です。**"
                   "先にビルドしてから当ててください"]

    ng, lines = [], []
    for f in found:
        # **1回だけ引きます。** 二度引くと、片方だけ潰したときに
        # 落ちずに例外になります（2026-09-07 の仕込みで踏みました）
        hits = [(t, resolve(t, root)) for t in SHA_RX.findall(f.name)]
        hits = [(t, full) for t, full in hits if full]
        dirty = bool(DIRTY_RX.search(f.name))
        if hits:
            full = hits[0][1]
            mark = "・**汚れた木から作られています**（中身はどの版とも一致しません）" \
                if dirty else ""
            lines.append(f"  {f.name}  ← {full[:12]}{mark}")
        else:
            ng.append(f)

    if ng:
        out = ["**配った物から、どのコードで作ったか分かりません:**"]
        for f in ng:
            out.append(f"  - {f.name}")
        out += [
            "  **名前にコミットを入れてください。**形は決めません——"
            "この repo に実在するコミットが名前から取り出せれば通ります。",
            "  Android の先例:",
            "    `iichoshi-walk-<版>-<YYYY-MM-DD>-<SHA>.apk`（aub-familywalk）",
            "    `FlashEnglish-<flavor>-<YYYYMMDD>-<SHA>[-dirty].apk`（FlashEnglish）",
            "  **汚れた木から作ったなら `-dirty` を入れてください。**"
            "その SHA は中身を指していません。",
            "  （数えるのは**配布物の中身に入るものだけ**。`git status` 全体で見ると"
            "記録を1行書いただけで毎回付き、目印の意味を失います）",
        ]
        if lines:
            out.append("  素性が取れているもの:")
            out += lines
        return 1, out

    return 0, [f"配った物の素性: **{len(found)} 件すべて取れます**"] + lines


def self_test():
    """**素性の無い名前で落ちること**が本体（妨害テスト）。"""
    import tempfile
    ok = True

    def ck(c, m):
        nonlocal ok
        if not c:
            ok = False
            print(f"  NG: {m}")

    exe = shutil.which("git")
    if not exe:
        print("git がありません。**確かめられないので 2**", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        subprocess.run([exe, "init", "-q"], cwd=str(root), check=True)
        subprocess.run([exe, "config", "user.email", "t@t"], cwd=str(root), check=True)
        subprocess.run([exe, "config", "user.name", "t"], cwd=str(root), check=True)
        (root / "a.txt").write_text("x", encoding="utf-8")
        subprocess.run([exe, "add", "-A"], cwd=str(root), check=True)
        subprocess.run([exe, "commit", "-qm", "i"], cwd=str(root), check=True)
        _, sha = _git(["rev-parse", "--short", "HEAD"], root)

        out = root / "out"; out.mkdir()

        # 1) 配布物が無い → **2**（0 にしない）
        rc, lines = check([out], root)
        ck(rc == 2, f"配布物が無いのに 2 を返さない: {rc}")
        ck(any("見ていない" in x for x in lines), "0件を綺麗と読ませない文言が無い")

        # 2) **iOS がいま出す名前 → 落ちる**（ここが本体）
        (out / "Runner.ipa").write_bytes(b"x")
        rc, lines = check([out], root)
        ck(rc == 1, f"**素性の無い Runner.ipa を通した**: {rc}")
        ck(any("Runner.ipa" in x for x in lines), "どれが駄目かを出していない")

        # 3) aub の形 → 通る
        (out / "Runner.ipa").unlink()
        (out / f"iichoshi-walk-1.0.0-2026-09-07-{sha}.apk").write_bytes(b"x")
        rc, _ = check([out], root)
        ck(rc == 0, f"aub の形を落とした: {rc}")

        # 4) FlashEnglish の形（flavor と dirty）→ 通る。**dirty を報せる**
        (out / f"FlashEnglish-release-20260907-{sha}-dirty.apk").write_bytes(b"x")
        rc, lines = check([out], root)
        ck(rc == 0, f"FlashEnglish の形を落とした: {rc}")
        ck(any("汚れた木" in x for x in lines), "dirty を報せていない")

        # 5) **実在しないコミットは通さない**（形だけ真似ても駄目）
        for f in out.iterdir():
            f.unlink()
        (out / "MyApp-1.0.0-2026-09-07-deadbee.ipa").write_bytes(b"x")
        rc, _ = check([out], root)
        ck(rc == 1, f"**実在しないコミットを通した**: {rc}")

        # 6) 完全な SHA でも通る
        for f in out.iterdir():
            f.unlink()
        _, full = _git(["rev-parse", "HEAD"], root)
        (out / f"MyApp-{full}.ipa").write_bytes(b"x")
        rc, _ = check([out], root)
        ck(rc == 0, f"完全な SHA を落とした: {rc}")

        # 7) **版番号をコミットと読み違えない**（1.0.0 は 16 進に見えない）
        for f in out.iterdir():
            f.unlink()
        (out / "MyApp-1.0.0.ipa").write_bytes(b"x")
        rc, _ = check([out], root)
        ck(rc == 1, f"版番号だけの名前を通した: {rc}")

        # 8) 配布物でないファイルは数えない（ディレクトリを渡したとき）
        for f in out.iterdir():
            f.unlink()
        (out / "README.txt").write_text("x", encoding="utf-8")
        rc, _ = check([out], root)
        ck(rc == 2, f"配布物でないものを数えた: {rc}")

        # 9) git のリポジトリでなければ **2**
        with tempfile.TemporaryDirectory() as td2:
            o2 = Path(td2) / "o"; o2.mkdir()
            (o2 / f"MyApp-{sha}.ipa").write_bytes(b"x")
            rc, _ = check([o2], Path(td2))
            ck(rc == 2, f"リポジトリの外なのに 2 を返さない: {rc}")

        # 10) **入口（main）まで通す**
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = main(["--root", str(root), str(out)])
        ck(rc == 2, f"入口が配布物なしで 2 を返さない: {rc}")
        (out / "Runner.ipa").write_bytes(b"x")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = main(["--root", str(root), str(out)])
        ck(rc == 1, f"入口が素性なしで 1 を返さない: {rc}")
        (out / "Runner.ipa").unlink()
        (out / f"MyApp-{sha}.ipa").write_bytes(b"x")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = main(["--root", str(root), str(out)])
        ck(rc == 0, f"入口が素性ありで 0 を返さない: {rc}")

    print("self-test: OK" if ok else "self-test: NG")
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="配った物から、どのコードで作ったかが分かるか")
    ap.add_argument("paths", nargs="*", default=["build"],
                    help="配布物、またはそれが入っている置き場")
    ap.add_argument("--root", type=Path, default=Path("."),
                    help="コミットの実在を照合するリポジトリ")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    rc, lines = check(a.paths or ["build"], a.root)
    for x in lines:
        print(x, file=sys.stderr if rc else sys.stdout)
    if rc == 2:
        return 2
    if rc != 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
