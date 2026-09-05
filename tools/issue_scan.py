#!/usr/bin/env python3
"""前回の走査以降の会話を切り出す。課題を見つけるのは AI、切り出すのは機械。

  issue_scan.py --collect        前回以降の会話をファイルに出す
  issue_scan.py --mark <ts>      そこまで走査したことを記録する
  issue_scan.py --status         前回いつまで走査したかを見る

**--mark は「いま」ではなく「実際に読んだ最後の記録の時刻」を書く。**
「いま」を書くと、走査してから記録するまでの間の発言が永久に落ちる。
"""
import argparse, json, os, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

STATE = "design/issue-scan.json"
PROJECTS = Path.home() / ".claude" / "projects"
MAX_CHARS = 400_000          # これを超えたら**黙って切らずに報告する**
KINDS = ("user", "assistant")


def encoded_dirs(root: Path):
    """その案件の会話記録がある置き場をすべて返す（サブディレクトリで作業した分も拾う）。"""
    if not PROJECTS.is_dir():
        return []
    want = str(root.resolve()).replace("/", "-")
    return [d for d in PROJECTS.iterdir()
            if d.is_dir() and (d.name == want or d.name.startswith(want + "-"))]


def sessions_by_cwd(root: Path, limit_days=30):
    """**案件の外で開いたセッション**を、記録の中身から見つける（2026-09-04・#31）。

    実害（2026-09-03）: qnd-database の作業を `~/.claude` で開いたセッションから
    行ったため、記録は `projects/-Users-nishikawakoki--claude/` に入った。
    `--status` は「この案件の会話記録が見つかりません」で止まり、
    **「どこまで見たかを機械が持つ」という肝が働かなかった。** 結果、課題を
    人が思い出して立てることになった。

    `CLAUDE.md` は「ハーネスのある案件は原則そのプロジェクト直下で開く」と
    定めているが、**外から触ることは実際に起きる。**

    置き場の名前（cwd の符号化）ではなく、**記録の中の `cwd`** で判定する。
    走査が重くなるので、直近に触られたファイルだけを見る。
    """
    if not PROJECTS.is_dir():
        return []
    import time
    want = str(root.resolve())
    cutoff = time.time() - limit_days * 86400
    mine = {d.resolve() for d in encoded_dirs(root)}
    out = []
    for d in PROJECTS.iterdir():
        if not d.is_dir() or d.resolve() in mine:
            continue
        for f in d.glob("*.jsonl"):
            try:
                if f.stat().st_mtime < cutoff:
                    continue
                with f.open(encoding="utf-8", errors="ignore") as fh:
                    for line in fh:
                        if '"cwd"' not in line:
                            continue
                        try:
                            rec = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        cwd = rec.get("cwd") or ""
                        if cwd == want or cwd.startswith(want + "/"):
                            out.append(f)
                            break
            except OSError:
                continue
    return sorted(set(out))


def load_state(root: Path):
    f = root / STATE
    if not f.exists():
        return {"last_scanned": None, "history": []}
    return json.loads(f.read_text(encoding="utf-8"))


def save_state(root: Path, st):
    f = root / STATE
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def text_of(rec):
    m = rec.get("message") or {}
    c = m.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(x.get("text", "") for x in c
                         if isinstance(x, dict) and x.get("type") == "text")
    return ""


def collect(root: Path, since, extra=None):
    """(記録の一覧, 読めなかった置き場) を返す。時刻順に並べる。

    `extra` は**案件の外で開いたセッション**の記録（#31）。
    """
    dirs = encoded_dirs(root)
    files = [f for d in dirs for f in sorted(d.glob("*.jsonl"))]
    files += [f for f in (extra or []) if f not in files]
    out, unreadable = [], []
    for f in files:
        if True:
            try:
                lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError as e:
                unreadable.append(f"{f}: {e}")
                continue
            for line in lines:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get("type") not in KINDS:
                    continue
                ts = r.get("timestamp")
                if not ts or (since and ts <= since):
                    continue
                t = text_of(r).strip()
                if t:
                    out.append({"ts": ts, "who": r["type"], "text": t,
                                "session": f.stem, "branch": r.get("gitBranch")})
    out.sort(key=lambda x: x["ts"])
    return out, unreadable


def render(root: Path, recs, since, unreadable):
    head = [
        f"# {root.name} の会話（課題を探すための材料）",
        "",
        f"- 走査した範囲: {since or '（記録の最初から）'} 〜 {recs[-1]['ts'] if recs else '—'}",
        f"- 記録の数: {len(recs)} 件",
        "- **入っているもの**: あなたと私の発言だけ",
        "- **入っていないもの**: 道具の出力、ファイルの中身、思考",
    ]
    if unreadable:
        head += ["", "**読めなかった置き場があります:**"] + [f"  - {u}" for u in unreadable]
    head += ["", "---", ""]

    body, total, cut_at = [], 0, None
    for r in recs:
        block = f"## {r['ts']} — {'あなた' if r['who']=='user' else '私'}\n\n{r['text']}\n"
        if total + len(block) > MAX_CHARS:
            cut_at = r["ts"]
            break
        body.append(block)
        total += len(block)

    if cut_at:
        head.insert(1, "")
        head.insert(2, f"**入りきらないので {cut_at} で止めました。**"
                       f" ここまでの課題を出したあと `--mark {cut_at}` で記録し、"
                       f" もう一度 `--collect` を回すと続きが出ます。")
    return "\n".join(head) + "\n".join(body), cut_at


def main(argv=None):
    ap = argparse.ArgumentParser(description="前回の走査以降の会話を切り出す")
    ap.add_argument("--root", default=".")
    ap.add_argument("--collect", action="store_true", help="会話を切り出してファイルに出す")
    ap.add_argument("--transcript", nargs="*",
                    help="会話記録を明示する（案件の外で開いたセッションを渡す）")
    ap.add_argument("--mark", metavar="TS", help="ここまで走査したと記録する（--collect が出した時刻）")
    ap.add_argument("--filed", type=int, default=0, help="--mark と一緒に、立てた課題の数を残す")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--since", help="状態ファイルを無視して、この時刻以降を見る")
    ap.add_argument("--out", help="書き出し先（省くと一時ファイル）")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)

    if a.self_test:
        return self_test()

    root = Path(a.root).resolve()
    st = load_state(root)

    if a.status:
        print(f"案件: {root}")
        print(f"前回の走査: {st['last_scanned'] or '（まだ一度も走査していません）'}")
        for h in st["history"][-5:]:
            print(f"  {h['at'][:19]}  〜{h['scanned_until'][:19]}  "
                  f"記録{h['records']}件 / 課題{h.get('issues_filed', 0)}件")
        dirs = encoded_dirs(root)
        outside = sessions_by_cwd(root)
        if not dirs and not outside:
            print("**この案件の会話記録が見つかりません。**\n"
                  "  この案件で開いたセッションも、外から触ったセッションも"
                  "ありません。", file=sys.stderr)
            return 2
        print(f"会話記録の置き場: {len(dirs)} 箇所"
              + (f" / **案件の外で開いたセッション {len(outside)} 本**"
                 if outside else ""))
        for f in outside[:5]:
            print(f"  外: {f.parent.name}/{f.name}")
        return 0

    if a.mark:
        st["last_scanned"] = a.mark
        st["history"].append({
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "scanned_until": a.mark,
            "records": st.pop("_pending_records", 0),
            "issues_filed": a.filed,
        })
        save_state(root, st)
        print(f"{a.mark} まで走査したと記録しました（課題 {a.filed} 件）")
        return 0

    if not a.collect:
        ap.print_help()
        return 2

    since = a.since or st["last_scanned"]
    dirs = encoded_dirs(root)
    # **案件の外で開いたセッションも拾う**（#31）。`--transcript` があればそれを足す
    outside = [Path(x) for x in (a.transcript or [])] or sessions_by_cwd(root)
    if not dirs and not outside:
        print(f"**{root} の会話記録が見つかりません。**\n"
              f"  {PROJECTS} に置き場が無く、記録の中に cwd が {root} のものも"
              f"ありません。\n"
              f"  この案件のセッションで実行するか、--transcript で記録を"
              f"指してください。", file=sys.stderr)
        return 2
    if outside and not a.transcript:
        print(f"**案件の外で開いたセッション {len(outside)} 本も見ます**"
              f"（記録の中の cwd で判定）。")

    recs, unreadable = collect(root, since, outside)
    if not recs:
        print(f"前回の走査（{since}）以降、新しい発言はありません。")
        return 0

    text, cut_at = render(root, recs, since, unreadable)
    out = Path(a.out) if a.out else Path(tempfile.gettempdir()) / f"issue-scan-{root.name}.md"
    out.write_text(text, encoding="utf-8")

    until = cut_at or recs[-1]["ts"]
    st["_pending_records"] = len(recs)
    save_state(root, st)

    print(f"書き出しました: {out}")
    print(f"  範囲: {since or '最初'} 〜 {until}")
    print(f"  記録: {len(recs)} 件 / {len(text):,} 文字")
    if cut_at:
        print(f"  **入りきらず {cut_at} で止めました。** 続きは再度 --collect してください。")
    if unreadable:
        print(f"  **読めなかった置き場が {len(unreadable)} 件あります。**")
    print(f"\n課題を立て終えたら:  issue_scan.py --root {root} --mark {until} --filed <件数>")
    return 0


def self_test():
    import shutil
    ok = True
    def check(cond, msg):
        nonlocal ok
        if not cond:
            ok = False; print(f"  NG: {msg}")

    tmp = Path(tempfile.mkdtemp())
    try:
        root = tmp / "proj"; (root / "design").mkdir(parents=True)
        pdir = tmp / "projects" / str(root.resolve()).replace("/", "-")
        pdir.mkdir(parents=True)
        sub = tmp / "projects" / (str(root.resolve()).replace("/", "-") + "-sub")
        sub.mkdir(parents=True)

        def rec(ts, who, txt):
            return json.dumps({"type": who, "timestamp": ts,
                               "message": {"content": [{"type": "text", "text": txt}]}},
                              ensure_ascii=False)
        (pdir / "a.jsonl").write_text("\n".join([
            rec("2026-01-01T00:00:00Z", "user", "古い発言"),
            rec("2026-02-01T00:00:00Z", "user", "検査が落ちました"),
            rec("2026-02-01T00:01:00Z", "assistant", "生成器が壊れています"),
            "こわれた行",
            json.dumps({"type": "system", "timestamp": "2026-02-01T00:02:00Z"}),
        ]), encoding="utf-8")
        (sub / "b.jsonl").write_text(rec("2026-02-01T00:00:30Z", "user", "サブでの発言"), encoding="utf-8")

        g = globals(); keep = g["PROJECTS"]; g["PROJECTS"] = tmp / "projects"
        try:
            # 置き場を2つとも拾う
            check(len(encoded_dirs(root)) == 2, "サブディレクトリの置き場を拾えていない")

            # **案件の外で開いたセッションを、記録の中の cwd で見つける**（#31）
            outside = PROJECTS / "-Users-someone--claude"
            outside.mkdir(parents=True, exist_ok=True)
            (outside / "s.jsonl").write_text(
                json.dumps({"type": "user", "timestamp": "2026-03-01T00:00:00Z",
                            "cwd": str(root.resolve()),
                            "message": {"content": "外から触った"}},
                           ensure_ascii=False) + "\n", encoding="utf-8")
            found = sessions_by_cwd(root)
            check(len(found) == 1 and found[0].name == "s.jsonl",
                  f"外で開いたセッションを見つけられない: {found}")
            # **別の案件のセッションは拾わない**
            (outside / "other.jsonl").write_text(
                json.dumps({"type": "user", "timestamp": "2026-03-01T00:00:00Z",
                            "cwd": "/どこか/別の案件",
                            "message": {"content": "無関係"}},
                           ensure_ascii=False) + "\n", encoding="utf-8")
            check(len(sessions_by_cwd(root)) == 1, "別の案件のセッションを拾った")
            # collect が外の記録も読む
            recs, _ = collect(root, None, sessions_by_cwd(root))
            check(any("外から触った" in (r.get("text") or "") for r in recs),
                  "外で開いたセッションの中身を読めていない")

            # --since より後だけ、時刻順に出る
            recs, bad = collect(root, "2026-01-15T00:00:00Z")
            check(len(recs) == 3, f"件数が違う（{len(recs)}）**壊れた行や system を混ぜていないか**")
            check([r["ts"] for r in recs] == sorted(r["ts"] for r in recs), "時刻順になっていない")
            check(recs[1]["text"] == "サブでの発言", "**別の置き場の発言が混ざっていない**")

            out = tmp / "o.md"
            rc = main(["--root", str(root), "--collect", "--since", "2026-01-15T00:00:00Z", "--out", str(out)])
            check(rc == 0, "--collect が落ちた")
            body = out.read_text(encoding="utf-8")
            check("古い発言" not in body, "**--since より前の発言が出ている**")
            check("検査が落ちました" in body, "--since より後の発言が出ていない")

            # --mark は「いま」ではなく渡された時刻を書く
            main(["--root", str(root), "--mark", "2026-02-01T00:01:00Z", "--filed", "2"])
            st = load_state(root)
            check(st["last_scanned"] == "2026-02-01T00:01:00Z", "**--mark がいまの時刻を書いている**")
            check(st["history"][-1]["issues_filed"] == 2, "立てた課題の数が残っていない")

            # 記録した後は、同じ発言が二度出ない
            recs2, _ = collect(root, st["last_scanned"])
            check(recs2 == [], "**記録したのに同じ発言がまた出る**")
            check(main(["--root", str(root), "--collect"]) == 0, "新着なしで落ちた")

            # 入りきらないときは黙って切らない
            g["MAX_CHARS"] = 50
            recs3, _ = collect(root, "2026-01-15T00:00:00Z")
            txt, cut = render(root, recs3, None, [])
            check(cut is not None, "**入りきらないのに切ったと言わない**")
            check("入りきらないので" in txt, "切った旨が本文に出ていない")
            g["MAX_CHARS"] = 400_000

            # 会話記録が無い案件は、黙って0件にせず落ちる
            empty = tmp / "none"; (empty / "design").mkdir(parents=True)
            check(main(["--root", str(empty), "--collect"]) == 2,
                  "**記録が無いのに「新着なし」で通している**")
            check(main(["--root", str(root), "--status"]) == 0, "--status が落ちた")
        finally:
            g["PROJECTS"] = keep
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
