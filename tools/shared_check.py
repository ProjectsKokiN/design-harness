#!/usr/bin/env python3
"""「自分の機体だけ緑」を止める（2026-09-04 新設・#44 / #51 / #42 / #56）。

## 何を見るか

段8 の課題は、根が1つです。**git のブランチという境界と、共有物の境界がずれている。**

| 何が届いていないか | 実害 |
|---|---|
| 自動検査そのもの（#44） | 数時間、検査が1度も動いていないのに、動いていると思って直し続けた |
| デザインの書き出し（#51） | 2日間、1台でしか通らない状態だった |
| 3台への依頼書（#42） | 527行の依頼が2日間、相手に届いていなかった |
| 変更の説明（#56） | 入っていない変更を「入っている」と書き、2台に無駄なビルドをさせた |

**症状も同じです。自分の機体だけ緑で、他の機体が赤くなって初めて分かります。**

## 4つの面（どれもネットワークも認証も要りません）

    python3 tools/shared_check.py --conflict            # #44
    python3 tools/shared_check.py --registry ~/dev/design-systems   # #51
    python3 tools/shared_check.py --shared design/machine-scope.json  # #42
    python3 tools/shared_check.py --claims design/pr-claims.json     # #56

`--conflict` は `git merge-tree` で衝突を見ます。**衝突していると GitHub は
マージ参照を作れず、workflow を起動しません。** 赤でもなく緑でもなく「無い」
という状態で、PR の画面には前回の結果が残るので、人も AI も赤い理由を探し続けます。

`--registry` は隣接クローン（submodule ではない）が**既定ブランチに居て、
未コミットを持っていないか**を見ます。ブランチに居ると、その機体だけが新しい
データを持ち、**他のどの機体で取っても古いまま**になります。

`--shared` は `machine-scope.json` の `shared`（3台の受信箱）が
**既定ブランチにあるか**を見ます。受信箱をブランチに置いた瞬間、受信箱として
機能しなくなります。

`--claims` は「このブランチに入っているはず」の宣言を、**実際の差分と
突き合わせます**。PR の説明は他機体が行動を決める根拠になるので、間違っていると
実機を持つ機体が動いてから分かります（1往復ぶん無駄になる）。

## 捕まえないもの

- 変更の**中身が正しいか**。ここは「共有されているか」だけを見ます
- 上流の最新（取りに行きません）。**取りに行っていないことは必ず言います**
- 確かめた方法: --self-test（合成したリポジトリで4面とも落ちること）
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）


def run(*args, cwd=None):
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=cwd)


def default_ref(cwd):
    """上流の既定ブランチ。**main を決め打ちしない。**"""
    r = run("symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD", cwd=cwd)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    for name in ("origin/main", "origin/master"):
        if run("rev-parse", "--verify", "-q", name, cwd=cwd).returncode == 0:
            return name
    return None


def check_conflict(root):
    """既定ブランチと衝突していないか（#44）。

    衝突していると GitHub は `refs/pull/N/merge` を作れず、**workflow を
    起動しません。** `gh pr view` の `mergeStateStatus` は `DIRTY` になります。
    **赤でもなく緑でもなく「無い」。**
    """
    ref = default_ref(root)
    if ref is None:
        return [f"  上流の既定ブランチが分かりません（origin/HEAD も main も master も）"]
    head = run("rev-parse", "HEAD", cwd=root).stdout.strip()
    base = run("rev-parse", ref, cwd=root).stdout.strip()
    if head == base:
        return []
    r = run("merge-tree", "--write-tree", ref, "HEAD", cwd=root)
    # 衝突があると 1 を返し、出力に CONFLICT の行が並ぶ
    if r.returncode == 0 and "CONFLICT" not in r.stdout:
        return []
    files = sorted(set(re.findall(r"CONFLICT \([^)]*\): (?:Merge conflict in )?(\S+)",
                                  r.stdout)))
    return [f"  **{ref} と衝突しています。**\n"
            f"    衝突していると GitHub はマージ参照を作れないので、"
            f"**CI が1度も起動しません。**\n"
            f"    赤でも緑でもなく「無い」状態になり、PR の画面には前回の結果が"
            f"残ります。\n"
            + (f"    衝突: {' / '.join(files[:8])}\n" if files else "")
            + f"    先に {ref} を取り込んで解いてください。"]


def check_registry(path):
    """隣接クローンが既定ブランチに居て、未コミットが無いか（#51）。"""
    p = Path(path).expanduser()
    if not (p / ".git").exists():
        return [f"  レジストリが git リポジトリではありません: {p}"]
    ref = default_ref(p)
    if ref is None:
        return [f"  レジストリの既定ブランチが分かりません: {p}"]
    cur = run("rev-parse", "--abbrev-ref", "HEAD", cwd=p).stdout.strip()
    want = ref.split("/", 1)[1]
    errs = []
    if cur != want:
        errs.append(f"  **レジストリが `{cur}` に居ます**（既定は `{want}`）: {p}\n"
                    f"    この機体だけが新しいデータを持ち、"
                    f"**他のどの機体で取っても古いまま**です。\n"
                    f"    2日間、1台でしか通らない状態をつくった形です。")
    dirty = run("status", "--porcelain", cwd=p).stdout.strip()
    if dirty:
        n = len(dirty.splitlines())
        errs.append(f"  **レジストリに未コミットが {n} 件あります**: {p}\n"
                    f"    その変更はこの機体にしかありません。\n"
                    + "\n".join(f"      {l}" for l in dirty.splitlines()[:6]))
    ahead = run("rev-list", "--count", f"{ref}..HEAD", cwd=p).stdout.strip()
    if ahead.isdigit() and int(ahead) > 0:
        errs.append(f"  **レジストリが {ahead} コミット先に居ます**（push 前）: {p}\n"
                    f"    push するまで他の機体には届きません。")
    return errs


def check_shared(root, conf_path):
    """3台の受信箱が、既定ブランチにあるか（#42）。"""
    p = Path(conf_path)
    if not p.exists():
        return [f"  担当の宣言がありません: {p}"]
    try:
        shared = json.loads(p.read_text(encoding="utf-8")).get("shared") or []
    except (OSError, json.JSONDecodeError) as e:
        return [f"  担当の宣言が読めません: {p}: {e}"]
    if not shared:
        return []
    ref = default_ref(root)
    if ref is None:
        return [f"  上流の既定ブランチが分かりません"]
    head = run("rev-parse", "--abbrev-ref", "HEAD", cwd=root).stdout.strip()
    if head == ref.split("/", 1)[1]:
        return []                       # 既定ブランチで作業しているなら届く
    diff = run("diff", "--name-only", f"{ref}...HEAD", cwd=root).stdout.split()
    stuck = []
    for s in shared:
        for f in diff:
            if f == s or (s.endswith("/") and f.startswith(s)):
                stuck.append(f)
    if not stuck:
        return []
    return [f"  **共有物の変更が枝（{head}）に取り残されています**（{len(stuck)}件）。\n"
            f"    受信箱は3台が読む場所です。**枝に置いた瞬間、受信箱として"
            f"機能しなくなります。**\n"
            f"    " + " / ".join(sorted(set(stuck))[:8])
            + ("…" if len(set(stuck)) > 8 else "") + "\n"
            f"    {ref} へ先に出すか、共有物だけを小さく分けて出してください。"]


def check_claims(root, conf_path):
    """「入っているはず」の宣言を、実際の差分と突き合わせる（#56）。"""
    p = Path(conf_path)
    if not p.exists():
        return [f"  宣言がありません: {p}\n"
                f"    **説明の裏取りを誰もしていません。**"]
    try:
        conf = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return [f"  宣言が読めません: {p}: {e}"]
    ref = default_ref(root)
    if ref is None:
        return ["  上流の既定ブランチが分かりません"]
    diff = set(run("diff", "--name-only", f"{ref}...HEAD", cwd=root).stdout.split())
    errs = []
    for f in conf.get("files", []):
        if f not in diff:
            errs.append(f"  宣言した `{f}` が、このブランチの差分にありません。\n"
                        f"    **入っていないものを「入っている」と書いています。**")
    for g in conf.get("greps", []):
        f, pat = g.get("file"), g.get("pattern")
        want = int(g.get("min", 1))
        if not f or not pat:
            errs.append(f"  grep の宣言に file か pattern がありません: {g}")
            continue
        target = root / f
        n = 0
        if target.exists():
            n = len(re.findall(pat, target.read_text(encoding="utf-8",
                                                     errors="ignore")))
        if n < want:
            errs.append(f"  宣言した `{pat}` が {f} に {n} 件しかありません"
                        f"（{want} 件以上のはず）。")
    return errs


def main(argv=None):
    ap = argparse.ArgumentParser(description="共有されているかを見る")
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--conflict", action="store_true", help="#44 既定ブランチとの衝突")
    ap.add_argument("--registry", type=Path, help="#51 隣接クローンの置き場")
    ap.add_argument("--shared", type=Path, help="#42 machine-scope.json")
    ap.add_argument("--claims", type=Path, help="#56 入っているはずの宣言")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    root = args.root.resolve()
    if not (root / ".git").exists():
        r = run("rev-parse", "--show-toplevel", cwd=root)
        if r.returncode != 0:
            print(f"git リポジトリではありません: {root}", file=sys.stderr)
            return 2
        root = Path(r.stdout.strip())

    errs, ran = [], []
    if args.conflict:
        ran.append("衝突")
        errs += check_conflict(root)
    if args.registry:
        ran.append("レジストリ")
        errs += check_registry(args.registry)
    if args.shared:
        ran.append("受信箱")
        errs += check_shared(root, args.shared)
    if args.claims:
        ran.append("説明の裏取り")
        errs += check_claims(root, args.claims)

    if not ran:
        print("見る面を1つも指定していません"
              "（--conflict / --registry / --shared / --claims）。\n"
              "  **何も見ていません。**", file=sys.stderr)
        return 2
    if errs:
        print(f"共有されていないものがあります（{' / '.join(ran)}）:", file=sys.stderr)
        print("\n".join(errs), file=sys.stderr)
        return 1
    print(f"共有の検査（{' / '.join(ran)}）: 問題ありません。"
          f"**上流は取りに行っていません**（手元の参照で見ています）。")
    return 0


def self_test():
    import tempfile
    ok = True

    def g(*a, cwd):
        return run(*a, cwd=cwd)

    def repo(path, branch="main"):
        path.mkdir(parents=True, exist_ok=True)
        g("init", "-q", "-b", branch, cwd=path)
        g("config", "user.email", "t@t", cwd=path)
        g("config", "user.name", "t", cwd=path)
        return path

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        up = repo(base / "up")
        (up / "a.txt").write_text("1\n", encoding="utf-8")
        (up / "MACHINE_TASKS.md").write_text("依頼\n", encoding="utf-8")
        g("add", "-A", cwd=up); g("commit", "-qm", "1", cwd=up)

        work = base / "work"
        g("clone", "-q", str(up), str(work), cwd=base)
        g("config", "user.email", "t@t", cwd=work)
        g("config", "user.name", "t", cwd=work)
        (work / "design").mkdir()
        (work / "design" / "machine-scope.json").write_text(
            json.dumps({"shared": ["MACHINE_TASKS.md", "docs/"]}), encoding="utf-8")
        ms = str(work / "design" / "machine-scope.json")

        import contextlib, io

        def call(*a):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = main(["--root", str(work), *a])
            return rc, buf.getvalue()

        # ── #44 衝突 ──────────────────────────────────────────
        rc, out = call("--conflict")
        if rc != 0:
            print(f"self-test NG: 衝突が無いのに落ちた（{rc}）\n   {out[:300]}"); ok = False
        # 上流と手元で同じ行を別々に変える
        (up / "a.txt").write_text("上流\n", encoding="utf-8")
        g("add", "-A", cwd=up); g("commit", "-qm", "up", cwd=up)
        g("fetch", "-q", "origin", cwd=work)
        g("checkout", "-q", "-b", "mine", cwd=work)
        (work / "a.txt").write_text("手元\n", encoding="utf-8")
        g("add", "-A", cwd=work); g("commit", "-qm", "mine", cwd=work)
        rc, out = call("--conflict")
        if rc != 1 or "CI が1度も起動しません" not in out:
            print(f"self-test NG: 衝突を見逃した（{rc}）\n   {out[:300]}"); ok = False
        if "a.txt" not in out:
            print("self-test NG: 衝突したファイルを名指ししていない"); ok = False

        # ── #42 受信箱 ────────────────────────────────────────
        rc, out = call("--shared", ms)
        if rc != 0:
            print(f"self-test NG: 受信箱を触っていないのに落ちた（{rc}）"); ok = False
        (work / "MACHINE_TASKS.md").write_text("枝で書いた依頼\n", encoding="utf-8")
        g("add", "-A", cwd=work); g("commit", "-qm", "tasks", cwd=work)
        rc, out = call("--shared", ms)
        if rc != 1 or "受信箱として" not in out:
            print(f"self-test NG: 枝に取り残された受信箱を見逃した（{rc}）"); ok = False

        # ── #56 説明の裏取り ──────────────────────────────────
        cl = work / "claims.json"
        cl.write_text(json.dumps({"files": ["MACHINE_TASKS.md"]}), encoding="utf-8")
        rc, out = call("--claims", str(cl))
        if rc != 0:
            print(f"self-test NG: 本当に入っているのに落ちた（{rc}）\n   {out[:300]}")
            ok = False
        cl.write_text(json.dumps({"files": ["test/safe_area_test.dart"]}),
                      encoding="utf-8")
        rc, out = call("--claims", str(cl))
        if rc != 1 or "入っていないものを" not in out:
            print(f"self-test NG: 入っていない主張を通した（{rc}）"); ok = False
        cl.write_text(json.dumps({"greps": [
            {"file": "MACHINE_TASKS.md", "pattern": "枝で書いた", "min": 1}]}),
            encoding="utf-8")
        rc, _ = call("--claims", str(cl))
        if rc != 0:
            print(f"self-test NG: 実在する grep の主張で落ちた（{rc}）"); ok = False
        cl.write_text(json.dumps({"greps": [
            {"file": "MACHINE_TASKS.md", "pattern": "ない文字列", "min": 1}]}),
            encoding="utf-8")
        rc, out = call("--claims", str(cl))
        if rc != 1 or "しかありません" not in out:
            print(f"self-test NG: 存在しない grep の主張を通した（{rc}）"); ok = False

        # ── #51 レジストリ ────────────────────────────────────
        reg_up = repo(base / "regup")
        (reg_up / "t.json").write_text("{}\n", encoding="utf-8")
        g("add", "-A", cwd=reg_up); g("commit", "-qm", "1", cwd=reg_up)
        reg = base / "reg"
        g("clone", "-q", str(reg_up), str(reg), cwd=base)
        g("config", "user.email", "t@t", cwd=reg); g("config", "user.name", "t", cwd=reg)
        rc, out = call("--registry", str(reg))
        if rc != 0:
            print(f"self-test NG: 既定ブランチのレジストリで落ちた（{rc}）\n   {out[:300]}")
            ok = False
        g("checkout", "-q", "-b", "figma-reexport", cwd=reg)
        rc, out = call("--registry", str(reg))
        if rc != 1 or "他のどの機体で取っても古いまま" not in out:
            print(f"self-test NG: 枝に居るレジストリを通した（{rc}）"); ok = False
        g("checkout", "-q", "main", cwd=reg)
        (reg / "t.json").write_text('{"new": 1}\n', encoding="utf-8")
        rc, out = call("--registry", str(reg))
        if rc != 1 or "未コミット" not in out:
            print(f"self-test NG: 未コミットのレジストリを通した（{rc}）"); ok = False
        g("add", "-A", cwd=reg); g("commit", "-qm", "2", cwd=reg)
        rc, out = call("--registry", str(reg))
        if rc != 1 or "コミット先に居ます" not in out:
            print(f"self-test NG: push 前のレジストリを通した（{rc}）"); ok = False

        # 面を指定しなければ落ちる（**何も見ていない**）
        rc, out = call()
        if rc != 2 or "何も見ていません" not in out:
            print(f"self-test NG: 面の指定なしで通した（{rc}）"); ok = False
    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
