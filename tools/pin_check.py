#!/usr/bin/env python3
"""submodule のピンが上流の既定ブランチから遅れていないかを見る。

一本化の目的は「仕組みの更新を全プロジェクトへ届けること」だが、submodule は
ピンで固定されるため、各案件が取り込むまで届かない。「5案件に複製されて
乖離していた」が「5案件が古いピンに固定されて乖離する」に形を変えるだけになる。

## 2026-09-04 に作り直した（#60）

**この道具は在ったのに、無力化されていた。**

    # ci/app-pre-push（当時）
    python3 design/harness/tools/pin_check.py 2>/dev/null || true

**出力を捨てて、必ず成功します。** さらに実測で、この行を持っていたのは
3案件のうち aub だけだった（flash-compose と planttalk は0箇所）。

結果、flash-compose のピンは **ブランチの途中のコミット**で止まり、main から
**16コミット遅れ**ていた。**すでに直してある欠陥を、もう一度踏んだ。**

同じ日の実測では、4案件のピンが **9〜25コミット遅れ**ていた。

## 見るもの

| | 落とすか |
|---|---|
| ピンが上流の**既定ブランチに入っていない**（ブランチの途中を指している） | **落とす** |
| 既定ブランチから遅れている | 知らせるだけ（`--strict` で落とす） |
| 遅れの中に、**この案件が使っている道具の変更**が含まれる | 強く出す（`--strict` で落とす） |

**ブランチの途中を指しているときだけ、`--strict` 無しでも落とします。**
上流でそのブランチが消えたら取得できなくなる、直しようのない状態だからです。
遅れそのものは自然に増えるので、上げる判断は人がします。

「この案件が使っている道具」は**宣言しません。導出します**——`design/verify.sh` と
CI の YAML が呼んでいる `tools/*.py` を読み取って、遅れの中の変更と突き合わせます。

## 使い方（案件のルートで）

    python3 design/harness/tools/pin_check.py [--submodule design/harness] [--strict]

捕まえないもの: 上流の変更の中身（何が変わったかは design-harness の log を見る）
確かめた方法: --self-test（合成したリポジトリで、ブランチの途中を指すピンが
  落ちること・遅れが数えられること・道具の変更を名指しできることを確認する）
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

#: 遅れの上限。超えたら注意を出す（落とさない）
DEFAULT_MAX_BEHIND = 10

#: 段が呼んでいる道具の名前。**`tools/` が付かない形もある**
#: （flash-compose の CI は `$H/impl_coverage_check.py` と書く）。
#: 名前だけ拾って、submodule に実在する道具と突き合わせる
FILE_RX = re.compile(r"([a-z_][a-z0-9_]*\.py)")
#: 遅れの中で変わったファイル（こちらはパスで来るので tools/ が付く）
TOOL_RX = re.compile(r"tools/([a-z_][a-z0-9_]*\.py)")


def run(cmd, cwd=None):
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)


def default_ref(sub):
    """上流の既定ブランチ。**main を決め打ちしない。**

    origin/HEAD → origin/main → origin/master の順に見る。
    """
    r = run(["git", "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD"],
            cwd=sub)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    for name in ("origin/main", "origin/master"):
        if run(["git", "rev-parse", "--verify", "-q", name], cwd=sub).returncode == 0:
            return name
    return None


def project_tools(root, sub):
    """この案件が呼んでいる道具の名前。**宣言しない。導出する。**

    `design/verify.sh` と CI の YAML から `*.py` の名前を拾い、
    **submodule に実在する道具だけ**に絞る。`tools/` が付く書き方と
    `$H/foo.py` の書き方が混在しているので、名前で拾って実在で絞る。
    """
    have = {f.name for f in (sub / "tools").glob("*.py")} if (sub / "tools").is_dir() \
        else set()
    seen = set()
    files = [root / "design" / "verify.sh"]
    wf = root / ".github" / "workflows"
    if wf.exists():
        files += sorted(wf.glob("*.yml")) + sorted(wf.glob("*.yaml"))
    for f in files:
        if f.exists():
            seen |= set(FILE_RX.findall(f.read_text(encoding="utf-8", errors="ignore")))
    return (seen & have) if have else seen


def main(argv=None):
    ap = argparse.ArgumentParser(description="submodule ピンの遅れを知らせる")
    ap.add_argument("--submodule", type=Path, default=Path("design/harness"))
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--strict", action="store_true",
                    help="遅れていたら exit 1（既定は知らせるだけ）")
    ap.add_argument("--max-behind", type=int, default=DEFAULT_MAX_BEHIND,
                    help=f"この数を超えたら注意を出す（既定 {DEFAULT_MAX_BEHIND}）")
    ap.add_argument("--no-fetch", action="store_true",
                    help="上流を取りに行かない（self-test と、手元だけで見るとき）")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    sub = args.submodule
    if not (sub / ".git").exists() and not (sub / "engine").exists():
        print(f"submodule がありません: {sub}（git submodule update --init）",
              file=sys.stderr)
        return 2

    # **取りに行っていないなら「未確認」と言う。** 手元の origin/main は
    # submodule のクローンが最後に fetch した時点のもので、平気で古い
    # （2026-09-04 実測: --no-fetch で 3案件が「最新です」と出たが、
    #  実際は 9〜25 コミット遅れていた。**この道具自身の嘘**）
    stale = args.no_fetch
    if not args.no_fetch:
        fetch = run(["git", "fetch", "-q", "origin"], cwd=sub)
        if fetch.returncode != 0:
            # ネットワーク断で作業を止めない。ただし**必ず「未確認」と言う**
            print(f"上流を取得できませんでした（オフライン?）。"
                  f"手元にある参照で見ます:\n"
                  f"  {fetch.stderr.strip()[:160]}", file=sys.stderr)
            stale = True

    ref = default_ref(sub)
    if ref is None:
        print(f"上流の既定ブランチが分かりません: {sub}\n"
              f"  origin/HEAD も origin/main も origin/master もありません。",
              file=sys.stderr)
        return 2

    # 1) ピンが既定ブランチに入っているか。**入っていなければ落とす**
    on_ref = run(["git", "merge-base", "--is-ancestor", "HEAD", ref],
                 cwd=sub).returncode == 0
    if not on_ref:
        head = run(["git", "rev-parse", "--short", "HEAD"], cwd=sub).stdout.strip()
        print(f"**ピンが {ref} に入っていません**（{head}）。\n"
              f"  ブランチの途中を指しています。**上流でそのブランチが消えると、"
              f"このピンは取得できなくなります。**\n"
              f"  {ref} に入っているコミットへ動かしてください:\n"
              f"    git -C {sub} fetch origin && git -C {sub} checkout {ref}\n"
              f"    git add {sub}", file=sys.stderr)
        return 1

    # 2) 何コミット遅れているか
    behind = run(["git", "rev-list", "--count", f"HEAD..{ref}"], cwd=sub)
    if behind.returncode != 0:
        print(f"比較に失敗: {behind.stderr.strip()[:200]}", file=sys.stderr)
        return 2
    n = int(behind.stdout.strip() or 0)
    note = "（**未確認**: 上流を取りに行っていないので、手元の参照で見ています）" \
        if stale else ""
    if n == 0:
        print(f"design-harness のピンは最新です{note}。")
        return 0

    # 3) 遅れの中に、この案件が使っている道具の変更が含まれるか
    files = run(["git", "diff", "--name-only", f"HEAD..{ref}"], cwd=sub).stdout
    changed = set(TOOL_RX.findall(files))
    used = project_tools(args.root.resolve(), sub)
    hit = sorted(changed & used)

    log = run(["git", "log", "--oneline", f"HEAD..{ref}"], cwd=sub).stdout
    print(f"design-harness のピンが {ref} から {n} コミット遅れています{note}。")
    if hit:
        print(f"  **この案件が使っている道具が {len(hit)} 本変わっています**: "
              f"{' / '.join(hit)}")
        print(f"  取り込むまで、その直しはこの案件に届きません。")
    if n > args.max_behind:
        print(f"  遅れが {args.max_behind} を超えました。取り込みどきです。")
    print(f"  取り込む: git -C {sub} checkout {ref} && git add {sub}")
    print("  上流の変更:")
    print("\n".join(f"    {l}" for l in log.strip().splitlines()[:10]))
    return 1 if args.strict else 0


def self_test():
    """合成したリポジトリで確かめる。**ネットワークは使わない。**"""
    import tempfile
    ok = True

    def g(*a, cwd):
        return run(["git", *a], cwd=cwd)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        up = root / "up"
        up.mkdir()
        g("init", "-q", "-b", "main", cwd=up)
        g("config", "user.email", "t@t", cwd=up)
        g("config", "user.name", "t", cwd=up)
        (up / "engine").mkdir()
        (up / "engine" / "x.py").write_text("1\n", encoding="utf-8")
        (up / "tools").mkdir()
        (up / "tools" / "seed_check.py").write_text("1\n", encoding="utf-8")
        (up / "tools" / "other.py").write_text("1\n", encoding="utf-8")
        g("add", "-A", cwd=up)
        g("commit", "-qm", "1", cwd=up)
        base = g("rev-parse", "HEAD", cwd=up).stdout.strip()

        # main を3つ進める。うち1つは seed_check.py を触る
        for i, f in enumerate(("tools/seed_check.py", "engine/x.py", "tools/other.py")):
            (up / f).write_text(f"{i+2}\n", encoding="utf-8")
            g("add", "-A", cwd=up)
            g("commit", "-qm", f"変更 {f}", cwd=up)

        # main に入らない枝を1つ作る
        g("checkout", "-q", "-b", "side", base, cwd=up)
        (up / "engine" / "y.py").write_text("9\n", encoding="utf-8")
        g("add", "-A", cwd=up)
        g("commit", "-qm", "枝の途中", cwd=up)
        side = g("rev-parse", "HEAD", cwd=up).stdout.strip()
        g("checkout", "-q", "main", cwd=up)

        proj = root / "proj"
        (proj / "design").mkdir(parents=True)
        sub = proj / "design" / "harness"
        g("clone", "-q", str(up), str(sub), cwd=root)
        # この案件は seed_check.py を呼んでいる
        (proj / "design" / "verify.sh").write_text(
            'step "種まき" "$PY" "$HARNESS/tools/seed_check.py"\n', encoding="utf-8")

        import contextlib, io

        def at(rev, argv=()):
            g("checkout", "-q", rev, cwd=sub)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = main(["--submodule", str(sub), "--root", str(proj),
                           "--no-fetch", *argv])
            return rc, buf.getvalue()

        rc, out = at("origin/main")
        if rc != 0 or "最新です" not in out:
            print(f"self-test NG: 最新なのに落ちた（{rc}）\n   {out[:300]}"); ok = False
        # **取りに行っていないなら、必ず「未確認」と言う**（この道具自身の嘘を潰す）
        if "未確認" not in out:
            print("self-test NG: --no-fetch なのに未確認と言っていない"); ok = False

        # **ブランチの途中を指していたら、--strict 無しでも落ちる**（これが本体）
        rc, out = at(side)
        if rc != 1:
            print(f"self-test NG: 枝の途中のピンを通した（{rc}）"); ok = False
        if "入っていません" not in out or "消えると" not in out:
            print("self-test NG: 枝の途中である理由を書いていない"); ok = False

        # 遅れを数える
        rc, out = at(base)
        if rc != 0 or "3 コミット遅れ" not in out:
            print(f"self-test NG: 遅れの数が出ない（{rc}）\n   {out[:300]}"); ok = False
        # **この案件が使っている道具の変更を名指しする**
        if "seed_check.py" not in out or "使っている道具が 1 本" not in out:
            print("self-test NG: 使っている道具の変更を名指ししていない"); ok = False
        if "other.py" in out.split("上流の変更")[0]:
            print("self-test NG: 使っていない道具まで名指しした"); ok = False

        rc, _ = at(base, ["--strict"])
        if rc != 1:
            print(f"self-test NG: --strict で遅れを通した（{rc}）"); ok = False

        rc, out = at(base, ["--max-behind", "2"])
        if "取り込みどき" not in out:
            print("self-test NG: 上限を超えた注意が出ない"); ok = False
        rc, out = at(base, ["--max-behind", "9"])
        if "取り込みどき" in out:
            print("self-test NG: 上限内なのに注意を出した"); ok = False

        # 既定ブランチを決め打ちしない（master でも動く）
        g("branch", "-m", "main", "master", cwd=up)
        g("fetch", "-q", "origin", "+refs/heads/*:refs/remotes/origin/*", cwd=sub)
        g("update-ref", "-d", "refs/remotes/origin/main", cwd=sub)
        g("symbolic-ref", "-d", "refs/remotes/origin/HEAD", cwd=sub)
        rc, out = at(base)
        if "origin/master" not in out:
            print(f"self-test NG: master を既定ブランチとして見ていない\n   {out[:250]}")
            ok = False

        # submodule が無ければ 2
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            if main(["--submodule", str(root / "ない"), "--no-fetch"]) != 2:
                print("self-test NG: submodule が無いのに通した"); ok = False
    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
