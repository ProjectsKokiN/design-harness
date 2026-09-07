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

## 書式（2通り）

**案件の受信箱**（依頼はその案件の話）:

    ## YYYY-MM-DD 宛先: <宛先> [未対応|完了] — 要件
    対象の commit: main@<sha>（この依頼を書いたときの main）
    …本文…

**横断の受信箱**（`machine-relay`。依頼は別のリポジトリの話・2026-09-06・#88）:

    ## YYYY-MM-DD 宛先: <宛先> [未対応|完了] — 要件
    対象: <リポジトリ名>@<sha>

後者は `~/dev/<リポジトリ名>` を探して**そちらの HEAD と比べます**。
**「いま居るリポジトリ」で比べると、受信箱自身の sha を見て黙って通ります**
（#71 と同じ穴が横断の受信箱で開いていた）。対象のリポジトリが手元に無ければ
**確かめられないので落とします**（黙って通さない）。

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
#: 索引の見出しは案件で少し違う（FlashEnglish は「## 未対応の依頼」）。行頭の一致で探す
INDEX_HEAD_RX = re.compile(r"^## 未対応の依頼.*$", re.M)
TARGET_RX = re.compile(r"^対象の commit: (\w+)@([0-9a-f]{7,40})", re.M)
#: 横断の受信箱の書式（2026-09-06・#88）。`対象: <リポジトリ名>@<sha>`
#: 案件の受信箱は「いま居るリポジトリ」の話なので上の形。横断の受信箱は**別のリポジトリ**の話
CROSS_RX = re.compile(r"^対象: ([A-Za-z0-9._-]+)@([0-9a-f]{7,40})", re.M)
#: **横断の受信箱かどうかは、受信箱自身の書式の説明から導く**（2026-09-07・#89）。
#: ファイル名やパスで決め打ちにすると、置き場が増えたときに黙って案件の書式に戻ります
CROSS_DOC_RX = re.compile(r"^\s*対象: <リポジトリ名>@<sha>\s*$", re.M)
#: **文書そのものの見出し**（依頼の本文ではない）。節の終わりはここか、次の依頼か、索引。
#: 2026-09-07 まで「次の `## ` まで」で切っていたため、**本文が `## 小見出し` を使うと
#: そこで切れ、残りが受信箱に取り残されていた**（実測: 依頼2件なのに 5,097 行・
#: `## ` の見出し 309 個）。**移した行数を出す**ようにしたのも同じ日（下記）
STRUCT_RX = re.compile(
    r"^## (?:ビルドを頼むときの決まり|セッションログの書き方|完了した依頼の扱い|"
    r"見出しの書式|使い方|宛先|ここだけの決まり|なぜ案件と分けたか)", re.M)

#: 対象のリポジトリを探す場所
REPO_HOME = Path.home() / "dev"        # reachability-ok: ~/.claude ではなく開発の置き場


def find_repo(name):
    """対象のリポジトリの置き場を探す。

    ほとんどは `~/dev/<名前>` ですが、**スキルの置き場（`.claude`）はホーム直下**です
    （2026-09-06 に実際の依頼で当たった。`対象: .claude@8563a6a`）。
    見つからなければ None を返し、呼び出し側が落とします（黙って通さない）。
    """
    for d in (REPO_HOME / name, Path.home() / name):
        if (d / ".git").exists():
            return d
    return None
def is_cross(text):
    """横断の受信箱か。**宣言（ファイル名・パス）ではなく、受信箱が自分で説明している書式から導く。**

    machine-relay の `MACHINE_TASKS.md` は冒頭で `対象: <リポジトリ名>@<sha>` を要求しています。
    案件の受信箱（flash-compose / aub-familywalk）にはこの説明がありません。
    """
    return CROSS_DOC_RX.search(text) is not None


ARCHIVE_TITLE = "# マシン間の申し送り（完了ぶんの保管）"


def git(root, *args):
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def section_end(text, after: int) -> int:
    """節の終わり。**次の依頼の見出し・索引・文書の構造の見出し**のいちばん手前。

    **「次の `## `」で切ってはいけない。** 本文は `## 小見出し` を使うので、
    そこで切ると**残りが取り残される**（2026-09-07 に実際に起きた）。
    """
    ends = [len(text)]
    for rx in (HEAD_RX, INDEX_HEAD_RX, STRUCT_RX):
        m = rx.search(text, after)
        if m:
            ends.append(m.start())
    return min(ends)


def sections(text):
    """[(start, end, date, to, state, title)] — 見出しから節の終わりまで。"""
    out = []
    for m in HEAD_RX.finditer(text):
        out.append((m.start(), section_end(text, m.end()), m.group(1), m.group(2),
                    m.group(3), m.group(4)))
    return out


def index_line(date, to, title):
    return f"- {date} 宛先: {to} — **{title}**（**着手できます**）\n"


def do_add(path, root, to, title, body, date, with_target, target_repo=None):
    text = path.read_text(encoding="utf-8")
    idx = INDEX_HEAD_RX.search(text)
    if not idx:
        print(f"{path.name} に「{INDEX_HEAD}」の節がありません。**索引が無いと受け取る側が探せません。**"
              f"（受信箱が削られた形。git で戻してください）", file=sys.stderr)
        return 1
    cross = is_cross(text)
    if cross and target_repo is None and with_target:
        # **黙って案件の書式を書かない。** 案件の書式（`対象の commit: main@<sha>`）は
        # --check-target が「いま居るリポジトリ」と比べるので、**横断の受信箱では
        # 受信箱自身の sha を見て通ります**（#71 と同じ穴。2026-09-07 に実際に踏んだ）
        print(f"{path.name} は**横断の受信箱**です（冒頭が `対象: <リポジトリ名>@<sha>` を要求）。\n"
              f"  どのリポジトリの話か道具には分かりません。`--target-repo <リポジトリ名>` を付けてください。\n"
              f"  例: --target-repo design-harness\n"
              f"  対象を書かないなら --no-target です（**--check-target は対象なしを数えません**）",
              file=sys.stderr)
        return 2
    target = ""
    if with_target:
        if cross:
            where = find_repo(target_repo)
            if where is None:
                print(f"対象のリポジトリ `{target_repo}` が {REPO_HOME}/ にも {Path.home()}/ にも"
                      f"ありません。**sha を確かめられないので書きません**", file=sys.stderr)
                return 2
            rc, sha = git(where, "rev-parse", "--short=7", "HEAD")
            if rc != 0:
                print(f"`{target_repo}` の HEAD が取れません", file=sys.stderr)
                return 2
            target = f"対象: {target_repo}@{sha}\n\n"
        else:
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
        m = STRUCT_RX.search(text)
        pos = m.start() if m else idx.start()
    text = text[:pos] + section + text[pos:]
    i = INDEX_HEAD_RX.search(text).end()
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
    moved = block.count("\n")
    print(f"完了にして {archive.name} へ移しました（**{moved} 行**）: {date} 宛先: {to} — {title}")
    if moved < 5:
        # **短すぎる移動は、切り方をまちがえた形。** 2026-09-07 に 200 行の節が
        # 8 行として移り、残りが受信箱に取り残された（誰も気づかなかった）
        print(f"注意: {moved} 行しか移っていません。**節の切り方を確かめてください**"
              f"（本文が `## 小見出し` を使っていると、そこで切れる形が過去にありました）")
    return 0


def do_check_target(path, root, require_for):
    text = path.read_text(encoding="utf-8")
    secs = [s for s in sections(text) if s[4] == "未対応"]
    if not secs:
        print("未対応の依頼はありません（対象の commit を確かめるものが無い）")
        return 0
    req = re.compile(require_for) if require_for else None
    crossing = is_cross(text)
    errs, warns, seen = [], [], 0
    for s, e, date, to, _, title in secs:
        body = text[s:e]
        m = TARGET_RX.search(body)
        cross = CROSS_RX.search(body)
        if not m and not cross:
            if req and req.search(title):
                errs.append(f"  {date} 宛先: {to} — {title}: **ビルドの依頼に対象の commit がありません。**"
                            f"受け取った機体は「いまの main」で作るしかなく、古い版を配ります（#71）")
            continue
        if crossing and m and not cross:
            # **案件の書式は、横断の受信箱では確かめられない。** `main@<sha>` の `main` は
            # リポジトリ名ではなく、下の else 側は「いま居るリポジトリ」と比べます。
            # つまり **受信箱自身の sha を見て黙って通ります**（#71 と同じ穴・#89）
            errs.append(f"  {date} 宛先: {to} — {title}: **横断の受信箱に案件の書式"
                        f"（`対象の commit: ...`）が書かれています。** ここの決まりは "
                        f"`対象: <リポジトリ名>@<sha>` です。このままだと"
                        f"**受信箱自身の sha と比べて黙って通ります**")
            continue
        seen += 1
        if cross:
            # **横断の受信箱**（#88）。対象は別のリポジトリなので、そちらの HEAD と比べる。
            # ここを「いま居るリポジトリ」で比べると、**受信箱自身の sha を見て黙って通る**
            name, sha = cross.group(1), cross.group(2)
            where = find_repo(name)
            if where is None:
                errs.append(f"  {date} 宛先: {to} — {title}: 対象のリポジトリ `{name}` が "
                            f"{REPO_HOME}/ にも {Path.home()}/ にもありません。"
                            f"**確かめられないので通しません**"
                            f"（黙って通すと #71 と同じ穴が開きます）")
                continue
            target_root, label = where, f"{name}@{sha}"
        else:
            sha = m.group(2)
            target_root, label = root, sha
        rc, _ = git(target_root, "cat-file", "-e", f"{sha}^{{commit}}")
        if rc != 0:
            warns.append(f"  {date} — {title}: 対象 {label} がこの手元にありません（**取り込んでいない**）。"
                         f"git fetch / pull してから作ってください")
            continue
        rc, _ = git(target_root, "merge-base", "--is-ancestor", sha, "HEAD")
        if rc != 0:
            errs.append(f"  {date} 宛先: {to} — {title}: **いまの HEAD は依頼の対象（{label}）より古い。**"
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
    ap.add_argument("--target-repo", metavar="リポジトリ名",
                    help="横断の受信箱で `対象: <リポジトリ名>@<sha>` に書く対象（例: design-harness）")
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
                      args.body.read_text(encoding="utf-8"), args.date, not args.no_target,
                      args.target_repo)
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

        # ─── **本文が `## 小見出し` を使う節を、まるごと移せるか**（2026-09-07）───
        # ここが抜けていたので、**依頼2件なのに受信箱が 5,097 行**まで膨らんだ。
        # 見出しだけ移って本文が取り残され、**司令塔がその先を読んでいなかった**
        body3 = root / "b3.md"
        body3.write_text("前置き\n\n## 実測しました\n\n表\n\n## 結論\n\n終わり\n",
                         encoding="utf-8")
        run("--add", "--to", "Windows", "--title", "小見出しのある依頼", "--body", str(body3),
            "--date", "2026-09-07", "--no-target")
        rc, out = run("--complete", "小見出しのある依頼")
        t = inbox.read_text(encoding="utf-8")
        a = archive.read_text(encoding="utf-8")
        check(rc == 0, f"小見出しのある節を完了にできなかった（{rc}）")
        for s in ("## 実測しました", "## 結論", "終わり"):
            check(s not in t, f"**本文が受信箱に取り残された**: {s!r}")
            check(s in a, f"**本文がアーカイブに入っていない**: {s!r}")
        check("## セッションログの書き方" in t and "## ビルドを頼むときの決まり" in t,
              "**文書の構造の見出しまで移した**（切りすぎ）")

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
        # git の無い場所では対象の commit が取れない → 2（--no-target なら書ける）
        with tempfile.TemporaryDirectory() as td2:
            ib = Path(td2) / "MACHINE_TASKS.md"
            ib.write_text(f"# 受信箱\n\n{INDEX_HEAD}\n\n", encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = main(["--file", str(ib), "--root", td2, "--add", "--to", "Windows",
                           "--title", "x", "--body", str(body2)])
            check(rc == 2, f"git の無い場所で対象を取れないのに 2 で止まらなかった（{rc}）")
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = main(["--file", str(ib), "--root", td2, "--add", "--to", "Windows",
                           "--title", "x", "--body", str(body2), "--no-target"])
            check(rc == 0, f"--no-target なら git 無しでも足せるはず（{rc}）")

        # ─── 横断の受信箱（#88）: 対象は別のリポジトリ ───────────────
        cross = root / "cross.md"
        cross.write_text(
            f"# 横断の受信箱\n\n{INDEX_HEAD}\n\n"
            f"## 2026-09-06 宛先: Windows [未対応] — 別のリポジトリの話\n"
            f"対象: machine-relay-no-such-repo@{new}\n\n本文\n", encoding="utf-8")
        X = ["--file", str(cross), "--root", str(root)]
        b3 = io.StringIO()
        with contextlib.redirect_stdout(b3), contextlib.redirect_stderr(b3):
            rc = main(X + ["--check-target"])
        check(rc == 1 and "確かめられないので通しません" in b3.getvalue(),
              f"**対象のリポジトリが無いのに通した（{rc}）**\n   {b3.getvalue()[:200]}")
        # ホーム直下のリポジトリ（`.claude`）も探す（2026-09-06 に実際の依頼で当たった）
        check(find_repo("no-such-repo-anywhere") is None, "無いリポジトリを見つけたと言った")
        # 対象のリポジトリが手元にあれば、そちらの HEAD と比べる
        import machine_scope as _ms  # noqa: F401  （tools/ が sys.path に居ることの確認）
        global REPO_HOME
        keep_home = REPO_HOME
        REPO_HOME = root.parent
        try:
            cross.write_text(
                f"# 横断の受信箱\n\n{INDEX_HEAD}\n\n"
                f"## 2026-09-06 宛先: Windows [未対応] — 別のリポジトリの話\n"
                f"対象: {root.name}@{new}\n\n本文\n", encoding="utf-8")
            b4 = io.StringIO()
            with contextlib.redirect_stdout(b4), contextlib.redirect_stderr(b4):
                rc = main(X + ["--check-target"])
            check(rc == 0 and "対象あり 1 件" in b4.getvalue(),
                  f"対象のリポジトリの HEAD と比べられない（{rc}）\n   {b4.getvalue()[:250]}")
            # **受信箱自身の sha を見ていないこと。** 受信箱の HEAD には無い sha を対象にする
            cross.write_text(
                f"# 横断の受信箱\n\n{INDEX_HEAD}\n\n"
                f"## 2026-09-06 宛先: Windows [未対応] — 別のリポジトリの話\n"
                f"対象: {root.name}@deadbeefcafe1\n\n本文\n", encoding="utf-8")
            b5 = io.StringIO()
            with contextlib.redirect_stdout(b5), contextlib.redirect_stderr(b5):
                rc = main(X + ["--check-target"])
            check(rc == 0 and "取り込んでいない" in b5.getvalue(),
                  f"手元に無い対象を注意にしていない（{rc}）")
        finally:
            REPO_HOME = keep_home

        # ─── 横断の受信箱を**導く**（#89）: `--add` が案件の書式を書かないこと ─────
        # 2026-09-07 に実際に踏んだ。`--add` は横断の受信箱でも `対象の commit: main@<sha>`
        # を書き、`--check-target` はそれを**受信箱自身の sha と比べて黙って通していた**
        CROSS_DOC = ("# 横断の受信箱\n\n## 見出しの書式\n\n"
                     "    ## YYYY-MM-DD 宛先: <宛先> [未対応|完了] — 要件\n"
                     "    対象: <リポジトリ名>@<sha>\n\n")
        xbox = root / "xbox.md"
        Y = ["--file", str(xbox), "--root", str(root)]

        def yrun(*a):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = main(Y + list(a))
            return rc, buf.getvalue()

        # 書式の説明から導く。案件の受信箱（説明が無い）は False のまま
        check(is_cross(CROSS_DOC) is True, "横断の受信箱を横断と見なせない")
        check(is_cross(inbox.read_text(encoding="utf-8")) is False, "**案件の受信箱を横断と誤判定した**")

        # 仕込み: 横断の受信箱に案件の書式を置く → 落ちる（直す前は 0 で通った）
        xbox.write_text(CROSS_DOC + f"{INDEX_HEAD}\n\n"
                        f"## 2026-09-06 宛先: Windows [未対応] — 案件の書式が混ざった依頼\n\n"
                        f"対象の commit: main@{new}\n\n本文\n", encoding="utf-8")
        rc, out = yrun("--check-target")
        check(rc == 1 and "横断の受信箱に案件の書式" in out,
              f"**横断の受信箱で案件の書式を通した（{rc}）**\n   {out[:250]}")

        # --add: 対象のリポジトリを言わなければ書かない（黙って案件の書式にしない）
        xbox.write_text(CROSS_DOC + f"{INDEX_HEAD}\n\n", encoding="utf-8")
        rc, out = yrun("--add", "--to", "Windows", "--title", "x", "--body", str(body2),
                       "--date", "2026-09-06")
        check(rc == 2 and "--target-repo" in out,
              f"**横断の受信箱で対象なしのまま足した（{rc}）**\n   {out[:250]}")
        check("対象の commit:" not in xbox.read_text(encoding="utf-8"), "**案件の書式を書いてしまった**")

        # --add: 手元に無いリポジトリ名は書かない（sha を確かめられない）
        rc, out = yrun("--add", "--to", "Windows", "--title", "x", "--body", str(body2),
                       "--date", "2026-09-06", "--target-repo", "no-such-repo-anywhere")
        check(rc == 2 and "確かめられないので書きません" in out,
              f"無いリポジトリの対象を書いた（{rc}）\n   {out[:200]}")

        # --add: --no-target なら対象なしで足せる
        rc, _ = yrun("--add", "--to", "Windows", "--title", "対象なし", "--body", str(body2),
                     "--date", "2026-09-06", "--no-target")
        check(rc == 0, f"横断の受信箱に --no-target で足せない（{rc}）")

        # --add: --target-repo を渡すと横断の書式で書き、--check-target が通る
        REPO_HOME = root.parent
        try:
            xbox.write_text(CROSS_DOC + f"{INDEX_HEAD}\n\n", encoding="utf-8")
            rc, out = yrun("--add", "--to", "Windows", "--title", "対象あり", "--body", str(body2),
                           "--date", "2026-09-06", "--target-repo", root.name)
            tx = xbox.read_text(encoding="utf-8")
            check(rc == 0, f"--target-repo で足せない（{rc}）\n   {out[:250]}")
            check(CROSS_RX.search(tx) is not None, "**横断の書式（対象: <名前>@<sha>）で書いていない**")
            check("対象の commit:" not in tx, "**案件の書式も一緒に書いた**")
            rc, out = yrun("--check-target")
            check(rc == 0 and "対象あり 1 件" in out,
                  f"--add が書いた対象を --check-target が読めない（{rc}）\n   {out[:250]}")
        finally:
            REPO_HOME = keep_home

        # 索引の見出しが「## 未対応の依頼」だけの案件（FlashEnglish）でも足せる
        inbox.write_text(t.replace(INDEX_HEAD, "## 未対応の依頼"), encoding="utf-8")
        # **日付を渡す。** 渡さないと当日の日付で書かれ、下の照合（2026-09-05）と
        # 食い違う。**書いた日だけ通り、翌日から全機体で落ちる**（2026-09-06 に発生）。
        # 他の `--add` は全部 `--date` を渡していて、ここだけ抜けていた。
        rc, _ = run("--add", "--to", "Windows", "--title", "短い見出しの索引",
                    "--body", str(body2), "--date", "2026-09-05", "--no-target")
        t3 = inbox.read_text(encoding="utf-8")
        check(rc == 0 and "## 未対応の依頼\n\n- 2026-09-05 宛先: Windows — **短い見出しの索引**" in t3
              or rc == 0 and "- 2026-09-05 宛先: Windows — **短い見出しの索引**" in t3,
              f"短い索引の見出しに足せない（{rc}）")
        # 索引の節が無い受信箱には足せない（削られた形）
        inbox.write_text(t.replace(INDEX_HEAD, "## 索引ではない"), encoding="utf-8")
        rc, _ = run("--add", "--to", "Windows", "--title", "x", "--body", str(body2), "--no-target")
        check(rc == 1, f"索引の無い受信箱に足した（{rc}）")

    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
