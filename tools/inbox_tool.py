#!/usr/bin/env python3
"""受信箱（MACHINE_TASKS.md）の節を、regex を手で書かずに足す・完了にする・対象の commit を確かめる
（2026-09-05 新設・#69 / #71）。

## なぜ要るか

- **#69**: 依頼を完了にしてアーカイブへ移す操作の副作用で、受信箱が 3 回 33 行まで削られた。
  3 台とも同じ形で壊した（節を編集する道具が無く、毎回 regex を手で書いていた）
- **#71**: 依頼に「どの commit に対するものか」が無く、直す前の版が 2 回配布された。
  受け取った機体は「いまの main」で作るしかなく、想定した版かを確かめる手段が無かった

## 使い方（案件のルートで）

    # 依頼を足す（見出し・索引・対象の commit を機械が書く）
    python3 tools/inbox_tool.py --add --to "Mac mini / Windows" --title "要件" --body 本文.md

    # 依頼を完了にしてアーカイブへ移す（見出しを [完了] にし、索引の行も消す。**消さずに移す**）
    python3 tools/inbox_tool.py --complete "要件の一部"

    # 受け取る側: 自分の HEAD が依頼の対象より古くないか（古ければ取り込んでから作る）
    python3 tools/inbox_tool.py --check-target
    python3 tools/inbox_tool.py --check-target --require-for "ビルド|APK|TestFlight|配布"   # ビルドの依頼に対象が無ければ落とす

## 書式（machine-relay と同じ）

    ## YYYY-MM-DD 宛先: <宛先> [未対応|完了] — 要件
    対象の commit: main@<sha>（この依頼を書いたときの main）
    …本文…

    ## 未対応の依頼（索引）
    - YYYY-MM-DD 宛先: <宛先> — **要件**（**着手できます**）

## 捕まえないもの

- 本文の中身が正しいか。ここは節の出し入れと対象の commit だけ
- 確かめた方法: --self-test（足す→対象を確かめる→完了にする、の往復と、古い HEAD で落ちること）
"""

import argparse
import datetime
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

HEAD_RX = re.compile(r"^## (\d{4}-\d{2}-\d{2}) 宛先: (.+?) \[(未対応|完了)\] — (.+?)\s*$", re.M)
INDEX_HEAD = "## 未対応の依頼（索引）"
TARGET_RX = re.compile(r"^対象の commit: (\w+)@([0-9a-f]{7,40})", re.M)
ARCHIVE_TITLE = "# マシン間の申し送り（完了ぶんの保管）"


def git(root, *args):
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def sections(text):
    """[(start, end, date, to, state, title)] — 見出しから次の `## ` まで。"""
    heads = list(HEAD_RX.finditer(text))
    out = []
    for m in heads:
        nxt = re.compile(r"^## ", re.M).search(text, m.end())
        end = nxt.start() if nxt else len(text)
        out.append((m.start(), end, m.group(1), m.group(2), m.group(3), m.group(4)))
    return out


def index_line(date, to, title):
    return f"- {date} 宛先: {to} — **{title}**（**着手できます**）\n"


def do_add(path, root, to, title, body, date, with_target):
    text = path.read_text(encoding="utf-8")
    if INDEX_HEAD not in text:
        print(f"{path.name} に「{INDEX_HEAD}」の節がありません。**索引が無いと受け取る側が探せません。**"
              f"（受信箱が削られた形。git で戻してください）", file=sys.stderr)
        return 1
    target = ""
    if with_target:
        rc, sha = git(root, "rev-parse", "--short=12", "origin/main")
        branch = "main"
        if rc != 0:
            rc, sha = git(root, "rev-parse", "--short=12", "HEAD")
            branch = "HEAD"
        if rc != 0:
            print("対象の commit が取れません（git リポジトリではない？）。--no-target で書けます",
                  file=sys.stderr)
            return 2
        target = (f"対象の commit: {branch}@{sha}（この依頼を書いたときの {branch}。"
                  f"取り込んだ main がこれより**古ければ、先に取り込む**。新しければそのまま進む）\n\n")
    head = f"## {date} 宛先: {to} [未対応] — {title}\n\n"
    section = head + target + body.rstrip("\n") + "\n\n"
    secs = sections(text)
    if secs:
        pos = secs[0][0]                      # いちばん上の依頼の前（新しいものが上）
    else:
        m = re.search(r"^## (?:ビルドを頼むときの決まり|セッションログの書き方|完了した依頼の扱い)", text, re.M)
        pos = m.start() if m else text.index(INDEX_HEAD)
    text = text[:pos] + section + text[pos:]
    i = text.index(INDEX_HEAD) + len(INDEX_HEAD)
    nl = text.index("\n", i) + 1
    while nl < len(text) and text[nl] == "\n":
        nl += 1
    text = text[:nl] + index_line(date, to, title) + text[nl:]
    path.write_text(text, encoding="utf-8")
    print(f"足しました: {date} 宛先: {to} — {title}" + (f"（{target.splitlines()[0][:40]}…）" if target else ""))
    return 0


def do_complete(path, archive, query):
    text = path.read_text(encoding="utf-8")
    hits = [s for s in sections(text) if s[4] == "未対応" and (query in s[5] or query in f"{s[2]} 宛先: {s[3]}")]
    if len(hits) != 1:
        print(f"完了にする節が {len(hits)} 件当たりました（1 件に絞ってください）: {query!r}\n"
              + "\n".join(f"  - {s[2]} 宛先: {s[3]} — {s[5]}" for s in hits), file=sys.stderr)
        return 1 if hits else 2
    s, e, date, to, _, title = hits[0]
    block = text[s:e].replace("[未対応]", "[完了]", 1).rstrip("\n") + "\n\n"
    text = text[:s] + text[e:]
    # 索引の行を消す（日付と宛先で当てる。要件は書き換わることがある）
    lines = text.splitlines(keepends=True)
    keep, removed = [], 0
    for ln in lines:
        if ln.startswith(f"- {date} 宛先: {to} ") and (title in ln or removed == 0 and title[:12] in ln):
            removed += 1
            continue
        keep.append(ln)
    if removed != 1:
        print(f"注意: 索引の行が {removed} 件消えました（1 件のはず）。索引を目で確かめてください")
    path.write_text("".join(keep), encoding="utf-8")
    if archive.exists():
        a = archive.read_text(encoding="utf-8")
        if a.startswith(ARCHIVE_TITLE):
            nl = a.index("\n") + 1
            while nl < len(a) and a[nl] == "\n":
                nl += 1
            a = a[:nl] + block + a[nl:]
        else:
            a = a.rstrip("\n") + "\n\n" + block
    else:
        a = ARCHIVE_TITLE + "\n\n" + block
    archive.write_text(a, encoding="utf-8")
    print(f"完了にして {archive.name} へ移しました: {date} 宛先: {to} — {title}")
    return 0


def do_check_target(path, root, require_for):
    text = path.read_text(encoding="utf-8")
    secs = [s for s in sections(text) if s[4] == "未対応"]
    if not secs:
        print("未対応の依頼はありません（対象の commit を確かめるものが無い）")
        return 0
    req = re.compile(require_for) if require_for else None
    errs, warns, seen = [], [], 0
    for s, e, date, to, _, title in secs:
        body = text[s:e]
        m = TARGET_RX.search(body)
        if not m:
            if req and req.search(title):
                errs.append(f"  {date} 宛先: {to} — {title}: **ビルドの依頼に対象の commit がありません。**"
                            f"受け取った機体は「いまの main」で作るしかなく、古い版を配ります（#71）")
            continue
        seen += 1
        sha = m.group(2)
        rc, _ = git(root, "cat-file", "-e", f"{sha}^{{commit}}")
        if rc != 0:
            warns.append(f"  {date} — {title}: 対象 {sha} がこの手元にありません（**取り込んでいない**）。"
                         f"git fetch / pull してから作ってください")
            continue
        rc, _ = git(root, "merge-base", "--is-ancestor", sha, "HEAD")
        if rc != 0:
            errs.append(f"  {date} 宛先: {to} — {title}: **いまの HEAD は依頼の対象（{sha}）より古い。**"
                        f"このまま作ると直す前の版を配ります（aub で 2 回起きた）。先に取り込んでください")
    for w in warns:
        print(f"注意: {w.strip()}")
    print(f"対象の commit: 未対応 {len(secs)} 件のうち対象あり {seen} 件")
    if errs:
        print("依頼の対象と手元がそろっていません:", file=sys.stderr)
        print("\n".join(errs), file=sys.stderr)
        return 1
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="受信箱の節を道具で出し入れする")
    ap.add_argument("--file", type=Path, default=Path("MACHINE_TASKS.md"))
    ap.add_argument("--archive", type=Path, default=Path("MACHINE_TASKS_ARCHIVE.md"))
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--add", action="store_true", help="依頼を足す（--to --title --body）")
    ap.add_argument("--to", help="宛先（例: Mac mini / Windows）")
    ap.add_argument("--title", help="要件（見出しと索引に入る）")
    ap.add_argument("--body", type=Path, help="本文のファイル（Markdown）")
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    ap.add_argument("--no-target", action="store_true", help="対象の commit を書かない")
    ap.add_argument("--complete", metavar="要件の一部", help="節を [完了] にしてアーカイブへ移す")
    ap.add_argument("--check-target", action="store_true", help="HEAD が依頼の対象より古くないか")
    ap.add_argument("--require-for", metavar="正規表現",
                    help="--check-target で、要件がこれに当たる依頼には対象の commit を必須にする")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.file.exists():
        print(f"受信箱がありません: {args.file}", file=sys.stderr)
        return 2
    if args.add:
        if not (args.to and args.title and args.body):
            print("--add には --to --title --body が要ります", file=sys.stderr)
            return 2
        if not args.body.exists():
            print(f"本文のファイルがありません: {args.body}", file=sys.stderr)
            return 2
        return do_add(args.file, args.root, args.to, args.title,
                      args.body.read_text(encoding="utf-8"), args.date, not args.no_target)
    if args.complete:
        return do_complete(args.file, args.archive, args.complete)
    if args.check_target:
        return do_check_target(args.file, args.root, args.require_for)
    ap.print_help()
    return 2


def self_test():
    import contextlib
    import io
    import tempfile
    ok = True

    def check(cond, msg):
        nonlocal ok
        if not cond:
            print(f"self-test NG: {msg}"); ok = False

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        subprocess.run(["git", "init", "-q", "-b", "main", str(root)], capture_output=True)
        for kv in (("user.email", "t@t"), ("user.name", "t")):
            subprocess.run(["git", "-C", str(root), "config", *kv])
        inbox = root / "MACHINE_TASKS.md"
        archive = root / "MACHINE_TASKS_ARCHIVE.md"
        inbox.write_text(
            "# マシン間の申し送り\n\n## 見出しの書式\n\n    ## YYYY-MM-DD 宛先: <宛先> [未対応|完了] — 要件\n\n"
            "## 2026-09-01 宛先: Windows [未対応] — 既存の依頼\n\n本文A\n\n"
            "## ビルドを頼むときの決まり（**全マシン共通**）\n\n決まり\n\n"
            "## セッションログの書き方\n\n書き方\n\n"
            "## 完了した依頼の扱い\n\n移す\n\n"
            f"{INDEX_HEAD}\n\n- 2026-09-01 宛先: Windows — **既存の依頼**（**着手できます**）\n",
            encoding="utf-8")
        (root / "a.txt").write_text("1\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "1"], capture_output=True)
        body = root / "body.md"
        body.write_text("やること\n\n- 1つ目\n", encoding="utf-8")
        A = ["--file", str(inbox), "--archive", str(archive), "--root", str(root)]

        def run(*a):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = main(A + list(a))
            return rc, buf.getvalue()

        # 足す: 見出し・対象の commit・索引の 3 つが入る。既存の依頼の上に入る
        rc, out = run("--add", "--to", "Mac mini / Windows", "--title", "iOS と Android をビルド",
                      "--body", str(body), "--date", "2026-09-05")
        t = inbox.read_text(encoding="utf-8")
        check(rc == 0, f"足せなかった（{rc}）\n   {out}")
        check("## 2026-09-05 宛先: Mac mini / Windows [未対応] — iOS と Android をビルド" in t, "見出しが無い")
        check(TARGET_RX.search(t) is not None, "対象の commit が無い")
        check("- 2026-09-05 宛先: Mac mini / Windows — **iOS と Android をビルド**" in t, "索引の行が無い")
        check(t.index("2026-09-05 宛先") < t.index("2026-09-01 宛先"), "新しい依頼が上に入っていない")
        check("## セッションログの書き方" in t and "## ビルドを頼むときの決まり" in t, "**他の節を消した**")

        # 対象の確認: いまの HEAD は対象そのもの → 通る
        rc, out = run("--check-target")
        check(rc == 0 and "対象あり 1 件" in out, f"対象が HEAD なのに落ちた（{rc}）\n   {out}")
        # 対象を知らない sha にすり替える → 注意（取り込んでいない）で止めない
        t2 = TARGET_RX.sub("対象の commit: main@deadbeefcafe", t, count=1)
        inbox.write_text(t2, encoding="utf-8")
        rc, out = run("--check-target")
        check(rc == 0 and "取り込んでいない" in out, f"手元に無い対象を注意にしていない（{rc}）")
        inbox.write_text(t, encoding="utf-8")
        # HEAD を対象より古くする（別の枝で古い commit を指す）→ 落ちる
        rc_old, old = git(root, "rev-parse", "HEAD")
        (root / "a.txt").write_text("2\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "2"], capture_output=True)
        rc_new, new = git(root, "rev-parse", "--short=12", "HEAD")
        inbox.write_text(TARGET_RX.sub(f"対象の commit: main@{new}", inbox.read_text(encoding="utf-8"), count=1),
                         encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "3"], capture_output=True)
        subprocess.run(["git", "-C", str(root), "checkout", "-q", old], capture_output=True)
        # 古い HEAD には新しい受信箱が無いので、作業ツリーに置いて見る
        inbox.write_text(TARGET_RX.sub(f"対象の commit: main@{new}", t, count=1), encoding="utf-8")
        rc, out = run("--check-target")
        check(rc == 1 and "より古い" in out, f"HEAD が対象より古いのに落ちなかった（{rc}）\n   {out[:300]}")
        subprocess.run(["git", "-C", str(root), "checkout", "-q", "-f", "main"], capture_output=True)

        # ビルドの依頼に対象が無ければ落ちる（--require-for）
        body2 = root / "b2.md"; body2.write_text("x\n", encoding="utf-8")
        run("--add", "--to", "Windows", "--title", "APK を作り直す", "--body", str(body2),
            "--date", "2026-09-06", "--no-target")
        rc, out = run("--check-target", "--require-for", "ビルド|APK|TestFlight|配布")
        check(rc == 1 and "対象の commit がありません" in out, f"対象の無いビルド依頼を通した（{rc}）")
        rc, out = run("--check-target")
        check(rc == 0, "--require-for 無しで対象の無い依頼を落とした")

        # 曖昧な指定は止まる（3 件に当たる）
        rc, _ = run("--complete", "宛先:")
        check(rc == 1, f"複数に当たる指定を通した（{rc}）")

        # 完了にする: 節がアーカイブへ移り、索引の行が消え、他の節は残る
        rc, out = run("--complete", "APK を作り直す")
        t = inbox.read_text(encoding="utf-8")
        a = archive.read_text(encoding="utf-8")
        check(rc == 0, f"完了にできなかった（{rc}）\n   {out}")
        check("APK を作り直す" not in t, "完了した節が受信箱に残っている")
        check("## 2026-09-06 宛先: Windows [完了] — APK を作り直す" in a, "アーカイブに [完了] で入っていない")
        check(a.startswith(ARCHIVE_TITLE), "アーカイブの題が無い")
        check("- 2026-09-06 宛先: Windows" not in t, "索引の行が残っている")
        check("2026-09-05 宛先: Mac mini / Windows" in t and "2026-09-01 宛先: Windows" in t, "**別の依頼まで消した**")
        check("## セッションログの書き方" in t and INDEX_HEAD in t, "**必須の節を消した**（受信箱が削られる形）")
        rc, _ = run("--complete", "存在しない")
        check(rc == 2, f"当たらない指定で 2 で止まらなかった（{rc}）")
        # 索引の節が無い受信箱には足せない（削られた形）
        inbox.write_text(t.replace(INDEX_HEAD, "## 索引ではない"), encoding="utf-8")
        rc, _ = run("--add", "--to", "Windows", "--title", "x", "--body", str(body2), "--no-target")
        check(rc == 1, f"索引の無い受信箱に足した（{rc}）")

    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
