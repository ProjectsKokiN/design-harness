#!/usr/bin/env python3
"""**1 つのコミットが、2 つの担当にまたがっていないか**を見る（2026-09-20 新設）。

## なぜ「誰が触ったか」を見ないのか

同じ機体で複数のセッションが同じ作業ツリーを共有します（PlantTalk では
MacBook Air の上で Dev と PlantTalk の 2 セッション）。`machine_scope.py` は
**機体**で分けるので、ここは分けられません。

**セッションに名乗らせる形にはしません。**名乗りは自己申告で、誰も確かめません。
「自己申告で工程が飛ぶ」ことが、この案件でいちばん困っている穴です。

代わりに**混ざったかどうかだけ**を見ます。誰が書いたかは分からなくても、
**1 つのコミットが 2 人の持ち物を含んでいる**ことは機械で分かります。

## 何が止まるのか

実害（2026-09-20・PlantTalk）: 片方のセッションが自分の直しを commit しようとしたとき、
作業ツリーにはもう片方の**書きかけの画面 3 枚**が入っていました。`git add -A` を
打っていれば、書きかけがそのまま履歴に乗り、push で相手の作業が公開されます。
**このとき止めるものは何もありませんでした。**気づいたのは、たまたま
`git status` を読んだからです。

## 終了コード

    0 … 確かめて合格
    1 … 確かめて違反（1 つのコミットが 2 つの担当にまたがっている）
    2 … **確かめられなかった**（宣言が無い・見るコミットが 0 件）

## 設定（案件の design/session-scope.json）

    {
      "owners": {
        "Dev":       ["design/", "Sources/<名前>/Theme/"],
        "PlantTalk": ["Sources/<名前>/UI/", "Sources/<名前>/Catalog/"]
      },
      "shared": ["SESSION_LOG.md", "DECISIONS.md", "MACHINE_TASKS.md"],
      "またいでよい": {"<sha>": "理由"}
    }

`shared` はどの担当にも属さないので、混ざりの判定に数えません。
**`またいでよい` は空で置くこと。**埋めるときは理由を書きます。
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）


def git(root, *args):
    r = subprocess.run(["git", "-C", str(root), *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, r.stdout.strip()


def owner_of(path, owners, shared):
    """そのパスの持ち主を返す。shared と、どこにも当たらないものは None。"""
    for s in shared:
        if path == s or path.startswith(s.rstrip("/") + "/") or (s.endswith("/") and path.startswith(s)):
            return None
    hit, best = None, -1
    for name, paths in owners.items():
        for p in paths:
            # **長いほうを勝たせる。**`Sources/` と `Sources/X/UI/` が両方あるとき、
            # 細かいほうの持ち主にする
            if (path == p or path.startswith(p.rstrip("/") + "/")) and len(p) > best:
                hit, best = name, len(p)
    return hit


def commits_to_check(root):
    """押そうとしているコミットと、そのときの状態を返す。

    返す状態は 3 つです。**「押すものが無い」と「確かめられない」を分けます。**

        "ある"       … 押すコミットがある。中身を見る
        "押すもの無し" … 上流と同じ。**判断する対象が無いだけで、異常ではない**
        "履歴無し"    … コミットが 1 つも無い。**確かめられない**

    2026-09-20 に PlantTalk から指摘されて分けました。それまでは
    「押すものが無い」も 0 件として `2` を返しており、**押し切った直後は必ず
    落ちました。**何も悪いことをしていない状態で、次に押す人が自分と関係のない
    NG を 1 件抱えて始めることになります。

    **「0 件は綺麗ではなく見ていない」は、見るべきものが在るときの話です。**
    押すコミットが無いときは、見るべきものが無いだけです。
    """
    rc3, head = git(root, "rev-parse", "HEAD")
    if rc3 != 0 or not head:
        return [], "履歴無し"
    rc, up = git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if rc == 0 and up:
        rc2, out = git(root, "rev-list", f"{up}..HEAD")
        if rc2 == 0:
            shas = [c for c in out.splitlines() if c]
            return (shas, "ある") if shas else ([], "押すもの無し")
    # 上流が無い（枝を切った直後など）。HEAD だけ見る
    return [head], "ある"


def files_of(root, sha):
    rc, out = git(root, "show", "--name-only", "--pretty=format:", sha)
    return [l for l in out.splitlines() if l.strip()] if rc == 0 else []


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--self-test" in argv or "--selftest" in argv:
        return self_test()
    cfg_path = Path(argv[argv.index("--config") + 1]) if "--config" in argv else None
    if cfg_path is None or not cfg_path.exists():
        print(f"宣言がありません: {cfg_path or 'design/session-scope.json'}", file=sys.stderr)
        print("  **同じ作業ツリーを複数のセッションで使うなら、担当を宣言してください。**",
              file=sys.stderr)
        print('  {"owners": {"<名前>": ["<パス>"]}, "shared": [], "またいでよい": {}}',
              file=sys.stderr)
        return 2
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    root = Path(argv[argv.index("--root") + 1]) if "--root" in argv else cfg_path.resolve().parent.parent
    owners = cfg.get("owners") or {}
    shared = cfg.get("shared") or []
    allow = cfg.get("またいでよい") or {}
    if len(owners) < 2:
        print("担当が 2 つ未満です。**分けるものが無いなら、この段は要りません。**", file=sys.stderr)
        return 2

    shas, state = commits_to_check(root)
    if state == "押すもの無し":
        print("担当の混ざり: **押すコミットがありません**（上流と同じです）。見るものがありません")
        return 0
    if state == "履歴無し":
        print("コミットが 1 つもありません。**確かめられません。**", file=sys.stderr)
        return 2

    bad = []
    looked = 0
    for sha in shas:
        files = files_of(root, sha)
        if not files:
            continue
        looked += 1
        who = {}
        for f in files:
            o = owner_of(f, owners, shared)
            if o:
                who.setdefault(o, []).append(f)
        if len(who) > 1:
            if sha in allow or sha[:7] in allow:
                print(f"  またぎを宣言済み: {sha[:7]} — {allow.get(sha) or allow.get(sha[:7])}")
                continue
            bad.append((sha, who))

    print(f"担当の混ざり: コミット {looked} 件を見ました（担当 {len(owners)} / "
          f"どこにも属さない扱い {len(shared)} 件）")
    if bad:
        print("\n**1 つのコミットが 2 つの担当にまたがっています:**", file=sys.stderr)
        for sha, who in bad:
            rc, subj = git(root, "log", "-1", "--pretty=%s", sha)
            print(f"  - {sha[:7]} {subj}", file=sys.stderr)
            for name, fs in who.items():
                print(f"      {name}: {', '.join(fs[:4])}"
                      + (f" ほか {len(fs) - 4} 件" if len(fs) > 4 else ""), file=sys.stderr)
        print("\n  **相手の書きかけを巻き込んでいないか確かめてください。**", file=sys.stderr)
        print("  分けるなら `git reset --soft HEAD~1` してから、担当ごとに add し直します。",
              file=sys.stderr)
        print("  本当にまたぐ必要があるなら、`またいでよい` に sha と理由を書いてください。",
              file=sys.stderr)
        return 1
    return 0


def self_test() -> int:
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "design").mkdir()
        (root / "ui").mkdir()
        (root / "theme").mkdir()
        for a in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
            git(root, *a)

        def commit(paths, msg):
            for p in paths:
                f = root / p
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(f"{msg}\n", encoding="utf-8")
            # **`add -A` にしない。**設定ファイル自身（design/session-scope.json）を
            # 巻き込み、どのコミットも Dev の持ち物を含むことになる
            # （2026-09-20 に自分で踏みました）
            git(root, "add", *paths)
            git(root, "commit", "-q", "-m", msg)
            return git(root, "rev-parse", "HEAD")[1]

        cfg = {"owners": {"Dev": ["design/", "theme/"], "App": ["ui/"]},
               "shared": ["LOG.md"], "またいでよい": {}}
        cfgp = root / "design" / "session-scope.json"

        def write(c=None):
            cfgp.write_text(json.dumps(c or cfg, ensure_ascii=False), encoding="utf-8")

        def run():
            return main(["--config", str(cfgp), "--root", str(root)])

        write()
        commit(["design/a.txt"], "dev だけ")
        if run() != 0:
            print("self-test NG: 1 担当だけなのに落ちました"); ok = False

        sha = commit(["design/b.txt", "ui/c.txt"], "またいだ")
        if run() != 1:
            print("self-test NG: **またいだのに通しました**"); ok = False

        # **宣言すれば通る。**上流が無いときは HEAD しか見ないので、
        # **またいだコミットが HEAD のうちに**試します（2026-09-20 に順番を間違えました）
        c_allow = dict(cfg); c_allow["またいでよい"] = {sha: "作り直しのため"}
        write(c_allow)
        if run() != 0:
            print("self-test NG: 宣言したのに落ちました"); ok = False
        write()

        # **shared は数えない。**題材は**担当のパスの中にある shared**にします。
        # 外に置くと、shared を見なくてもどの担当にも当たらず、試験が効きません
        c_sh = {"owners": {"Dev": ["design/", "theme/"], "App": ["ui/"]},
                "shared": ["design/LOG.md"], "またいでよい": {}}
        write(c_sh)
        commit(["ui/d.txt", "design/LOG.md"], "shared 込み")
        if run() != 0:
            print("self-test NG: **shared を担当として数えました**"); ok = False
        write()

        # **長いパスが勝つ**（`src/` と `src/ui/` が両方あるとき）。
        # 題材は**両方を含むコミット**にします。片方だけだと、どちらの持ち主に
        # なっても「1 担当」で通ってしまい、試験が効きません
        c3 = {"owners": {"Dev": ["src/"], "App": ["src/ui/"]}, "shared": [], "またいでよい": {}}
        write(c3)
        commit(["src/x.txt", "src/ui/e.txt"], "細かいほうの持ち主")
        if run() != 1:
            print("self-test NG: **長いパスが勝っていません**"
                  "（src/ui/ が Dev の持ち物になり、またぎを見逃しました）"); ok = False
        write()

        # **担当が 1 つなら 2**
        c4 = {"owners": {"Dev": ["design/"]}, "shared": [], "またいでよい": {}}
        write(c4)
        if run() != 2:
            print("self-test NG: 担当 1 つで 2 を返しませんでした"); ok = False
        write()

        # **押すものが無いときは 0。**（2026-09-20・PlantTalk の指摘）
        # 押し切った直後は必ずこの状態になる。**何も悪いことをしていないのに
        # 落ちると、次に押す人が自分と関係のない NG を抱えて始める。**
        git(root, "remote", "add", "origin", str(root))
        git(root, "update-ref", "refs/remotes/origin/master", "HEAD")
        git(root, "branch", "--set-upstream-to=origin/master")
        if run() != 0:
            print("self-test NG: **押すものが無いのに落ちました**"); ok = False
        git(root, "branch", "--unset-upstream")

        # **コミットが 1 つも無ければ 2**
        with tempfile.TemporaryDirectory() as td2:
            empty = Path(td2)
            (empty / "design").mkdir()
            for a in (["init", "-q"], ["config", "user.email", "t@t"],
                      ["config", "user.name", "t"]):
                git(empty, *a)
            ecfg = empty / "design" / "session-scope.json"
            ecfg.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
            if main(["--config", str(ecfg), "--root", str(empty)]) != 2:
                print("self-test NG: **履歴が無いのに通しました**（確かめられないのに緑）"); ok = False

        # **宣言が無ければ 2**
        cfgp.unlink()
        if run() != 2:
            print("self-test NG: 宣言が無いのに 2 を返しませんでした"); ok = False

    print("self-test: " + ("OK" if ok else "NG"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
