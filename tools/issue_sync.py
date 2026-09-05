#!/usr/bin/env python3
"""直せていない課題を GitHub の Issue に写す（2026-09-02 新設）。

## なぜ要るか

**「直せていないが分かっている」ものは、すでに宣言されています。** ただし
散らばっていて、リポジトリのファイルを開かないと見えません。実測（2026-09-02）:

    宣言のある課題 83件 / 5種の書式 / 14ファイル

    allow・allow_tokens・notVerifiable   {why, reviewBy}
    entries（missing / font-substitutions）{reason, expires, decidedBy}
    $warn_only                            文字列（期限が文中にある）

さらに**宣言する場所が無い課題**は、行き場がありませんでした
（例: 2026-08-30 の FlashEnglish の所見は `FINDING-*.md` という
その場限りのファイルになった）。

**課題は Issue に集める。** 宣言はそのまま残し、この道具が写します。

## この道具の決まり

| | |
|---|---|
| 鍵 | Issue の本文に `<!-- harness-finding: <鍵> -->` を埋める。鍵は「ファイル:種類:名前」 |
| 作る | 宣言があって Issue が無ければ作る |
| 直す | 宣言が変わっていれば本文を更新する |
| **閉じる** | **宣言が消えていれば Issue を閉じる**（片付いたのに開いたままにしない） |
| 既定 | **--dry-run**（何が起きるかを出すだけ）。書くには `--apply` |
| 何を課題とするか | **期限が近い（既定30日）か過ぎたもの**、および `$warn_only` |

## 「課題」と「期限つきの決定」を分ける

宣言67件のうち **40件は `expectations.json` の `allow`** で、
「このテストは書き出しを読まない。見るのは木の構造だから」といった
**settled な判断**でした。全部を Issue にすると読まれなくなります。

**期限で自動的に分けます。** 期限が遠い宣言は「いまは決着している」、
近づいたら「やること」。手で印を付けないので、印の付け忘れが起きません。

- `$warn_only` は**常に課題**（関門が外れている状態そのものなので）
- 期限の宣言が無いものも**常に課題**（いつ見直すか決まっていない）
- `--due-within 9999` で全部を棚卸しできます

**CI からは書きません。** CI は「宣言と Issue がずれている」ことを知らせるだけです
（自動で作ると、通るたびに増えて誰も読まなくなります）。

## 宣言する場所が無い課題

`--new` で作ります。**理由と、何が分かれば閉じられるかを必ず書きます。**

    issue_sync.py --new --title "..." --why "..." --closes-when "..."

## この道具が捕まえないもの

- **宣言されていない課題**（誰も気づいていないもの）。それは各検査の仕事
- Issue 側で人が書いた内容（本文を上書きするのは鍵の節だけ）
- 確かめた方法: --self-test（宣言の収集・鍵の安定・閉じる判定）
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

MARK = "harness-finding"
MARK_RX = re.compile(rf"<!--\s*{MARK}:\s*(.+?)\s*-->")
SKIP_DIRS = ("node_modules", "__pycache__", "/build/", ".dart_tool", "/.git/",
             "/harness/")

#: 宣言の書式。語彙が割れているので、ここで1つに正規化する。
#: `what` / `why` / `how` / `blockedBy` / `issue` は aub-familywalk の
#: `remaining.json` が先に使っていた語彙（2026-09-02 に採用）。
WHY_KEYS = ("why", "reason")
DUE_KEYS = ("reviewBy", "expires")
WHAT_KEYS = ("what", "title")
HOW_KEYS = ("how",)
LIST_KEYS = ("allow", "allow_tokens", "notVerifiable", "entries")


def _name_of(e):
    for k in ("name", "id", "prefix", "file", "slot", "what"):
        if e.get(k):
            return str(e[k])
    return None


def findings(root: Path, extra_globs=()):
    """リポジトリの宣言を集めて、共通の形にして返す。

    **一覧を手で持たない。** 既知の書式を持つ JSON を探す
    （手で保守する一覧は古くなる、をこのリポジトリは何度も踏んでいる）。
    """
    out = []
    for f in sorted(root.rglob("*.json")):
        s = str(f)
        if any(x in s for x in SKIP_DIRS):
            continue
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(doc, dict):
            continue
        rel = f.relative_to(root).as_posix()

        w = doc.get("$warn_only")
        if w:
            body = w if isinstance(w, str) else (w.get("why") or "")
            due = None if isinstance(w, str) else w.get("reviewBy")
            out.append({
                "key": f"{rel}:warn_only", "file": rel, "kind": "$warn_only",
                "name": Path(rel).stem, "why": str(body), "due": due})

        for key in LIST_KEYS:
            v = doc.get(key)
            if not isinstance(v, list):
                continue
            for e in v:
                if not isinstance(e, dict):
                    continue
                why = next((e[k] for k in WHY_KEYS if e.get(k)), None)
                due = next((e[k] for k in DUE_KEYS if e.get(k)), None)
                name = _name_of(e)
                if not (why and name):
                    continue          # 理由の無いものは課題ではなく素のデータ
                out.append({
                    "key": f"{rel}:{key}:{name}", "file": rel, "kind": key,
                    "name": name, "why": str(why), "due": due,
                    "what": next((e[k] for k in WHAT_KEYS if e.get(k)), None),
                    "how": next((e[k] for k in HOW_KEYS if e.get(k)), None),
                    # **どのリポジトリの Issue にするか。** 案件で見つかっても
                    # 直す場所が共有層なら、Issue は共有層に立てる
                    "blockedBy": e.get("blockedBy"),
                    "issue": e.get("issue"),
                    "_path": None, "_list": key, "_idx": v.index(e)})
    return out


def is_open(fi, due_within):
    """いま課題として扱うか。

    **期限で分ける。** 期限が遠い宣言は「いまは決着している」、近づいたら
    「やること」。手で印を付けないので、印の付け忘れが起きない。
    """
    if fi["kind"] == "$warn_only":
        return True                     # 関門が外れている状態そのもの
    due = fi.get("due")
    if not due:
        return True                     # いつ見直すか決まっていない＝いま決める
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", str(due))
    if not m:
        return True                     # 読めない期限は宣言していないのと同じ
    from datetime import date
    try:
        d = date(*map(int, m.groups()))
    except ValueError:
        return True
    return (d - date.today()).days <= due_within


#: 仕組みの課題の行き先。`--new` の既定（#31）
HARNESS_REPO = "ProjectsKokiN/design-harness"


def target_repo(fi, default=None):
    """`blockedBy` から Issue を立てるリポジトリを決める。

    `owner/name` ならそのまま。名前だけなら `~/dev/<名前>` の origin を引く
    （**対応表を手で持たない**）。無ければ既定（そのリポジトリ自身）。
    """
    b = fi.get("blockedBy")
    if not b:
        return default
    if "/" in b:
        return b
    d = Path.home() / "dev" / b
    if not (d / ".git").exists():
        return default
    r = subprocess.run(["git", "-C", str(d), "remote", "get-url", "origin"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return default
    m = re.search(r"github\.com[:/](.+?)(?:\.git)?$", r.stdout.strip())
    return m.group(1) if m else default


def body_of(fi, repo_hint=""):
    due = fi["due"] or "（期限の宣言なし）"
    return (
        f"<!-- {MARK}: {fi['key']} -->\n\n"
        f"**この Issue は宣言から自動で作られています。** "
        f"宣言を消すと閉じます（`issue_sync.py --apply`）。\n\n"
        f"| | |\n|---|---|\n"
        f"| 宣言の場所 | `{fi['file']}` |\n"
        f"| 種類 | `{fi['kind']}` |\n"
        f"| 対象 | `{fi['name']}` |\n"
        f"| 期限 | {due} |\n\n"
        + (f"## 何が起きているか\n\n{fi['what']}\n\n" if fi.get("what") else "")
        + f"## なぜ直せていないか\n\n{fi['why']}\n\n"
        + (f"## 直し方\n\n{fi['how']}\n\n" if fi.get("how") else "")
        + f"## 閉じ方\n\n"
          f"直したうえで `{fi['file']}` から宣言を消し、`issue_sync.py --apply` を回す。"
          f"{repo_hint}\n")


def gh(args, repo=None):
    cmd = ["gh", *args]
    if repo:
        cmd += ["--repo", repo]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or r.stdout.strip())
    return r.stdout


def existing(repo=None):
    """開いている Issue のうち、鍵を持つものを 鍵 → (番号, 題, 本文) で返す。"""
    raw = gh(["issue", "list", "--state", "open", "--limit", "200",
              "--json", "number,title,body"], repo)
    out = {}
    for it in json.loads(raw or "[]"):
        m = MARK_RX.search(it.get("body") or "")
        if m:
            out[m.group(1)] = (it["number"], it["title"], it["body"])
    return out


def title_of(fi):
    head = (fi.get("what") or fi["why"]).strip().splitlines()[0]
    head = re.sub(r"\*\*", "", head)[:70]
    return f"[{fi['kind']}] {fi['name']} — {head}"


def main(argv=None):
    ap = argparse.ArgumentParser(description="直せていない課題を Issue に写す")
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--repo",
                    help=f"owner/name（省くと origin。ただし --new は "
                         f"{HARNESS_REPO}）")
    ap.add_argument("--apply", action="store_true", help="実際に書く（既定は下見）")
    ap.add_argument("--due-within", type=int, default=30, metavar="N",
                    help="期限が N 日以内か過ぎたものを課題とする（既定30）。"
                         "$warn_only と期限の宣言が無いものは常に課題")
    ap.add_argument("--new", action="store_true", help="宣言の場所が無い課題を1件作る")
    ap.add_argument("--title"); ap.add_argument("--why"); ap.add_argument("--closes-when")
    ap.add_argument("--inbox", action="store_true",
                    help="~/dev の全リポジトリの開いている課題を一覧する")
    ap.add_argument("--check", action="store_true",
                    help="**網に触らず**、Issue の無い課題を数えて落ちる（CI 用）")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    if args.inbox:
        # **溜まった課題を1コマンドで見る**（2026-09-02。運用の流れ:
        # 案件が Issue に溜め → 定期的に共有層のセッションがまとめて解く）
        repos, rows = [], []
        for d in sorted((Path.home() / "dev").iterdir()):
            if not (d / ".git").exists():
                continue
            r = target_repo({"blockedBy": d.name}, None)
            if r and r not in repos:
                repos.append(r)
        if not repos:
            print("~/dev に GitHub のリポジトリが見つかりません。", file=sys.stderr)
            return 2
        for r in repos:
            try:
                raw = gh(["issue", "list", "--state", "open", "--limit", "100",
                          "--json", "number,title,createdAt,labels"], r)
            except RuntimeError:
                continue                      # Issue を持たないリポジトリは飛ばす
            for it in json.loads(raw or "[]"):
                rows.append((r, it["number"], it["title"], it["createdAt"][:10]))
        rows.sort(key=lambda x: x[3])
        print(f"開いている課題: {len(rows)}件（{len(repos)}リポジトリを見ました）")
        cur = None
        for r, n, title, when in rows:
            if r != cur:
                print(f"\n  {r}")
                cur = r
            print(f"    #{n:<4} {when}  {title[:76]}")
        if not rows:
            print("  ありません。")
        return 0

    if args.check:
        # **CI からは Issue を作らない。** 通るたびに増えて誰も読まなくなる。
        # ここは「課題があるのに Issue が無い」ことを知らせるだけ
        found = findings(args.root.resolve())
        if not found:
            print(f"宣言が0件です: {args.root}\n"
                  f"  **『課題なし』ではなく『見ていない』かもしれません。**"
                  f"走査する場所を確かめてください。", file=sys.stderr)
            return 2
        opens = [f for f in found if is_open(f, args.due_within)]
        naked = [f for f in opens if not f.get("issue")]
        print(f"課題の台帳: 宣言 {len(found)}件 / いま課題 {len(opens)}件 / "
              f"Issue あり {len(opens) - len(naked)}件")
        if naked:
            print(f"\n**Issue の無い課題が {len(naked)} 件あります。**"
                  f" `issue_sync.py --apply` で起票してください:", file=sys.stderr)
            for f in naked:
                print(f"  - [{f['kind']}] {f['name']}（{f['file']}"
                      f"・期限 {f['due'] or 'なし'}）", file=sys.stderr)
            return 1
        print("  OK: いま課題としているものは全部 Issue になっています。")
        return 0

    if args.new:
        if not (args.title and args.why and args.closes_when):
            print("--new には --title / --why / --closes-when が要ります。\n"
                  "  **何が分かれば閉じられるか**を書かない課題は、"
                  "開いたまま忘れられます。", file=sys.stderr)
            return 2
        body = (f"## なぜ\n\n{args.why}\n\n## 閉じ方\n\n{args.closes_when}\n\n"
                f"*(宣言する場所が無い課題として `issue_sync.py --new` で作成)*\n")
        # **仕組みの課題は、仕組みのリポジトリへ立てる**（2026-09-04・#31）。
        # 既定が origin（案件のリポジトリ）だったため、`--repo` を付け忘れて
        # 仕組みの課題が案件側に立った（実際に1件立ててから閉じた）。
        # `--new` は「宣言する場所が無い＝仕組みの側の話」なので、
        # **既定を design-harness にする。** 案件へ立てたいときは --repo で明示する。
        repo = args.repo or HARNESS_REPO
        if not args.apply:
            print(f"[下見] 作る（{repo}）: {args.title}\n{body}")
            return 0
        if not args.repo:
            print(f"（--repo がありません。**仕組みのリポジトリ {repo} に立てます。**"
                  f"案件へ立てるなら --repo で指してください）")
        print(gh(["issue", "create", "--title", args.title, "--body", body],
                 repo).strip())
        return 0

    root = args.root.resolve()
    all_found = findings(root)
    open_all = [f for f in all_found if is_open(f, args.due_within)]
    # **既に Issue の URL を持つ宣言は作り直さない**（aub の remaining.json が
    # 先にこの形を使っていた。2026-09-02 に採用）
    filed = [f for f in open_all if f.get("issue")]
    found = {f["key"]: f for f in open_all if not f.get("issue")}
    later = len(all_found) - len(open_all)

    # **どのリポジトリの Issue にするか。** 案件で見つかっても直す場所が
    # 共有層なら、Issue は共有層に立てる（`blockedBy`）
    here = args.repo or target_repo({"blockedBy": root.name}, None)
    by_repo = {}
    for k, f in found.items():
        by_repo.setdefault(target_repo(f, here), {})[k] = f
    if None in by_repo:
        print("Issue を立てるリポジトリが決められません（origin も blockedBy も"
              "ありません）。--repo で指定してください。", file=sys.stderr)
        return 2
    try:
        have = {r: existing(r) for r in by_repo} or {here: existing(here)}
    except RuntimeError as e:
        print(f"GitHub の Issue が読めません: {e}", file=sys.stderr)
        return 2

    to_add, to_edit, to_close = [], [], []
    for r, fs in by_repo.items():
        h = have.get(r, {})
        to_add += [(r, f) for k, f in fs.items() if k not in h]
        to_edit += [(r, h[k][0], f) for k, f in fs.items()
                    if k in h and h[k][2].strip() != body_of(f).strip()]
    # 閉じるのは「このリポジトリ自身に立てた分」だけ見る（他所の Issue は
    # そこの宣言が正なので、こちらから閉じない）
    for k, (n, title, _) in have.get(here, {}).items():
        if k not in found and k.startswith(("design/", "")) and k not in \
                {f["key"] for f in all_found}:
            to_close.append((k, n, title, None))

    print(f"宣言 {len(all_found)}件 → いま課題とするもの {len(found)}件"
          f"（期限が {args.due_within} 日以内か過ぎたもの・$warn_only・期限の宣言なし）"
          f" / 先の宣言 {later}件は見送り")
    print(f"鍵を持つ Issue: {len(have)}件")
    print(f"  作る {len(to_add)} / 直す {len(to_edit)} / **閉じる {len(to_close)}**")
    if filed:
        print(f"  既に Issue がある宣言: {len(filed)}件（作り直しません）")
        for f in filed:
            print(f"    = {f['name']} → {f['issue']}")
    for r, f in to_add:
        print(f"  + [{r}] {title_of(f)}")
    for r, n, f in to_edit:
        print(f"  ~ [{r}] #{n} {title_of(f)}")
    for k, n, title, _ in to_close:
        print(f"  - #{n} {title}（宣言が消えました）")

    if not args.apply:
        if to_add or to_edit or to_close:
            print("\n**下見です。** 書くには --apply を付けてください。")
        return 0

    for r, f in to_add:
        url = gh(["issue", "create", "--title", title_of(f),
                  "--body", body_of(f)], r).strip()
        print(f"  作りました: {url}")
        # **URL を宣言に書き戻す。** 書き戻さないと、次に回したとき同じ
        # Issue をもう1つ作る（宣言と Issue が結びつかない）
        if write_back(root / f["file"], f["name"], url):
            print(f"    {f['file']} に issue の行を足しました")
    for r, n, f in to_edit:
        gh(["issue", "edit", str(n), "--title", title_of(f),
            "--body", body_of(f)], r)
        print(f"  直しました: [{r}] #{n}")
    for k, n, title, _ in to_close:
        gh(["issue", "close", str(n), "--comment",
            "宣言が消えたので閉じます（issue_sync）。"], here)
        print(f"  閉じました: #{n}")
    return 0


def write_back(path: Path, name: str, url: str) -> bool:
    """作った Issue の URL を宣言に書き戻す（同じ課題を二重に立てないため）。"""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    for key in LIST_KEYS:
        v = doc.get(key)
        if not isinstance(v, list):
            continue
        for e in v:
            if isinstance(e, dict) and _name_of(e) == name and not e.get("issue"):
                e["issue"] = url
                path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")
                return True
    return False


def self_test():
    import tempfile
    ok = True

    def check(cond, msg):
        nonlocal ok
        if not cond:
            print(f"self-test NG: {msg}"); ok = False

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "a.json").write_text(json.dumps({
            "allow": [{"name": "x.py", "why": "案件ごとに違ってよい理由",
                       "reviewBy": "2026-12-31"},
                      {"name": "noreason.py"}],          # 理由なし → 課題でない
            "$warn_only": "段階導入。実装網羅 10/26 が残っている"}),
            encoding="utf-8")
        (root / "b.json").write_text(json.dumps({
            "entries": [{"id": "splash", "reason": "Figma が束縛していない",
                         "expires": "2026-11-30", "decidedBy": "ユーザー"}]}),
            encoding="utf-8")
        (root / "plain.json").write_text(json.dumps({"x": 1}), encoding="utf-8")

        fs = {f["key"]: f for f in findings(root)}
        check(len(fs) == 3, f"集めた件数が違う: {len(fs)} → {sorted(fs)}")
        check("a.json:allow:x.py" in fs, "allow を集めていない")
        check("a.json:warn_only" in fs, "$warn_only を集めていない")
        check("b.json:entries:splash" in fs, "entries を集めていない")
        check(not any("noreason" in k for k in fs),
              "**理由の無い行を課題にした**（素のデータと区別できていない）")
        check(fs["b.json:entries:splash"]["due"] == "2026-11-30",
              "expires を期限として読めていない")
        check(fs["a.json:allow:x.py"]["due"] == "2026-12-31",
              "reviewBy を期限として読めていない")

        # 鍵が本文から読み戻せる（作った Issue と宣言が結びつく）
        b = body_of(fs["a.json:allow:x.py"])
        m = MARK_RX.search(b)
        check(m and m.group(1) == "a.json:allow:x.py", "鍵を本文から読み戻せない")

        # 宣言を消したら、その鍵は集まらない（＝閉じる対象になる）
        (root / "a.json").write_text(json.dumps({"allow": []}), encoding="utf-8")
        fs2 = {f["key"]: f for f in findings(root)}
        check("a.json:allow:x.py" not in fs2, "宣言を消しても集め続けている")

        # **期限で分ける**（この回の本題）
        from datetime import date, timedelta
        soon = (date.today() + timedelta(days=5)).isoformat()
        far = (date.today() + timedelta(days=400)).isoformat()
        past = (date.today() - timedelta(days=1)).isoformat()
        mk = lambda due: {"kind": "allow", "due": due, "why": "x", "name": "n"}
        check(is_open(mk(soon), 30), "期限が近いのに課題にしない")
        check(not is_open(mk(far), 30), "**期限が遠いのに課題にした**（決着済みが埋もれる）")
        check(is_open(mk(past), 30), "期限を過ぎたのに課題にしない")
        check(is_open(mk(None), 30), "期限の宣言が無いのに課題にしない")
        check(is_open(mk("いつか"), 30), "読めない期限を通した")
        check(is_open({"kind": "$warn_only", "due": far, "why": "x"}, 30),
              "$warn_only は期限が遠くても課題のはず")
        check(is_open(mk(far), 9999), "--due-within を大きくしても出ない")

        # 走査が空でも落ちない（0件は0件と言う）
        check(findings(root / "no_such") == [], "無いディレクトリで例外")

        # --check は網に触らない（Issue の無い課題があれば落ちる）
        (root / "c.json").write_text(json.dumps({
            "entries": [{"id": "naked", "why": "直せていない理由", "expires": past}]}),
            encoding="utf-8")
        check(main(["--check", "--root", str(root)]) == 1,
              "Issue の無い課題があるのに通した")
        (root / "c.json").write_text(json.dumps({
            "entries": [{"id": "naked", "why": "直せていない理由", "expires": past,
                         "issue": "https://example.com/1"}]}), encoding="utf-8")
        check(main(["--check", "--root", str(root)]) == 0,
              "Issue がある課題で落ちた")
        check(main(["--check", "--root", str(root / "empty")]) == 2,
              "宣言0件を通した（空振り）")

        # --new は「閉じ方」が無ければ落ちる
        check(main(["--new", "--title", "t", "--why", "w"]) == 2,
              "--closes-when が無いのに通した")

        # --- 本体を網に触らず通す（gh を差し替える）------------------------
        g = globals()
        calls = []

        def fake_gh(args, repo=None):
            calls.append((tuple(args), repo))
            if args[:2] == ["issue", "list"]:
                # 既に1件立っている体（鍵つき）
                return json.dumps([{"number": 7, "title": "既存",
                                    "body": f"<!-- {MARK}: keep.json:entries:kept -->"}])
            if args[:2] == ["issue", "create"]:
                return "https://example.com/issues/9\n"
            return ""

        keep_gh = g["gh"]
        g["gh"] = fake_gh
        try:
            (root / "keep.json").write_text(json.dumps({
                "entries": [{"id": "kept", "why": "残っている理由", "expires": past}]}),
                encoding="utf-8")
            (root / "gone.json").write_text(json.dumps({"entries": []}),
                                            encoding="utf-8")

            # 下見では書かない
            calls.clear()
            rc = main(["--root", str(root), "--repo", "o/r"])
            check(rc == 0, "下見で落ちた")
            check(not any(a[0][:2] == ("issue", "create") for a in calls),
                  "**下見なのに Issue を作った**")

            # --apply で作り、**URL を宣言に書き戻す**
            (root / "new.json").write_text(json.dumps({
                "entries": [{"id": "fresh", "why": "新しい課題の理由",
                             "expires": past}]}), encoding="utf-8")
            calls.clear()
            main(["--root", str(root), "--repo", "o/r", "--apply"])
            check(any(a[0][:2] == ("issue", "create") for a in calls),
                  "--apply で Issue を作らなかった")
            doc = json.loads((root / "new.json").read_text(encoding="utf-8"))
            check(doc["entries"][0].get("issue") == "https://example.com/issues/9",
                  "**URL を宣言に書き戻していない**（次に回すと二重に立つ）")

            # 書き戻した後は作り直さない
            calls.clear()
            main(["--root", str(root), "--repo", "o/r", "--apply"])
            check(not any(a[0][:2] == ("issue", "create") and "fresh" in str(a)
                          for a in calls), "書き戻した課題をもう一度立てた")

            # 宣言が消えた Issue は閉じる
            calls.clear()
            (root / "keep.json").write_text(json.dumps({"entries": []}),
                                            encoding="utf-8")
            main(["--root", str(root), "--repo", "o/r", "--apply"])
            check(any(a[0][:2] == ("issue", "close") for a in calls),
                  "**宣言が消えたのに Issue を閉じない**")
        finally:
            g["gh"] = keep_gh

        # 題と本文（鍵が読み戻せることは上で見た。what が題に出るか）
        fi = {"key": "k", "file": "f.json", "kind": "entries", "name": "n",
              "why": "理由", "due": None, "what": "何が起きているか",
              "how": "直し方"}
        check("何が起きているか" in title_of(fi), "what を題に使っていない")
        check("直し方" in body_of(fi), "how を本文に出していない")

        # blockedBy が owner/name ならそのまま使う
        check(target_repo({"blockedBy": "o/r"}, "d/f") == "o/r",
              "blockedBy を使っていない")
        check(target_repo({}, "d/f") == "d/f", "既定に落ちていない")

        # **--new の既定は仕組みのリポジトリ**（#31。案件側に立てた事故がある）
        import io as _io, contextlib as _ctx
        b = _io.StringIO()
        with _ctx.redirect_stdout(b):
            main(["--new", "--title", "t", "--why", "w", "--closes-when", "c"])
        check(HARNESS_REPO in b.getvalue(),
              f"--new の既定が仕組みのリポジトリでない: {b.getvalue()[:120]}")
        b = _io.StringIO()
        with _ctx.redirect_stdout(b):
            main(["--new", "--title", "t", "--why", "w", "--closes-when", "c",
                  "--repo", "o/proj"])
        check("o/proj" in b.getvalue(), "--repo の指定が効いていない")

    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
