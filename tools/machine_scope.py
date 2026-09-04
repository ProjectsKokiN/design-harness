#!/usr/bin/env python3
"""検査の段を、その失敗を起こせる機体に結び直す（2026-08-30 新設）。

## なぜ要るか

`verify.sh` は push 前に**全マシンで**走る。そこに Figma の鮮度の段
（`FIGMA_TOKEN` が要り、無ければ落とす）を置いていたため、

- **Windows** … トークンが `.env` に無く、この段だけ落ちる
- **Mac mini** … トークンは読めているが HTTP 403 で落ちる

が起きた。両方ともユーザーにしか直せない状態で止まった。

この段が守るのは「**Figma を変えたのに書き出しを取り直していない**」状態で、
それを起こせるのは `design/` を触る機体だけ。Windows と Mac mini は `design/` を
触らないので、**自分には起こせない失敗を確かめるために**トークンを求められていた。

**段を減らすのではなく、責任のある機体に結び直す。**

## 3つの規律

1. **担当の機体では必須のまま。** そこで落ちなければ意味がない
2. **担当外の機体では、機体名と理由を出力に残して飛ばす。**
   黙って飛ばすのは、このハーネスが繰り返し踏んできた
   「通ったと出るのに何も見ていない」そのもの
3. **対の検査を置く。** 担当外と宣言した機体が担当外のパスを変えていたら落とす。
   飛ばした穴をここで塞ぐ

## 使い方

    # 機体名を出す
    machine_scope.py --config design/machine-scope.json --whoami

    # 担当なら実行、担当外なら理由つきで飛ばす（verify.sh の段に使う）
    machine_scope.py --config design/machine-scope.json --owns design/ \\
        -- python3 design/figma_freshness.py

    # 真偽だけ欲しいとき（shell で分岐する。0=担当 / 3=担当外）
    machine_scope.py --config design/machine-scope.json --test-owns design/

## `set -e` の下では、そのまま呼ばない

`--test-owns` は担当外で **3** を返す。`set -e`（`set -euo pipefail`）の下で
素で呼ぶと、**`case $?` に着く前にスクリプトごと死ぬ。**

実害（flash-compose・2026-09-03）: Mac mini と Windows が **2日間、
`design/verify.sh` の検査を一度も走らせていなかった。** 両機とも
`--no-verify` で push していた（決まりに反する状態）。
`exit 3` は `verify.sh` に1行も書かれていないので、grep しても見つからない。

安全な受け方は2つ。

    # (a) if で受ける（set -e は if の条件では働かない）
    if machine_scope.py --config ... --test-owns design/; then
      ...担当のときの処理...
    fi

    # (b) || で拾ってから分岐する
    rc=0
    machine_scope.py --config ... --test-owns design/ || rc=$?
    case $rc in
      0) ...担当... ;;
      3) : ;;                       # 担当外。理由は道具が出している
      *) echo "機体を判定できませんでした" >&2; exit 1 ;;
    esac

**分岐が要らないなら `--owns ... -- <コマンド>` を使う。**
こちらは担当外でも 0 を返すので、`set -e` の影響を受けない。

    # 対の検査: 担当外のパスを変えていないか
    machine_scope.py --config design/machine-scope.json --check

## 設定（design/machine-scope.json）

    {
      "machines": {
        "MacBook Air": ["lib/ui/", "lib/theme/", "design/"],
        "Mac mini":    ["ios/"],
        "Windows":     ["lib/data/", "lib/providers/", "lib/router/",
                        "lib/main.dart", "scripts/"]
      },
      "shared": ["SESSION_LOG.md", "MACHINE_TASKS.md", "docs/"]
    }

**機体名を verify.sh に直接書かない。** 担当は案件ごとに変わりうるので設定に置く。
役割の正本は `~/.claude/skills/machine-relay/references/worker.md`。

## この検査が捕まえないもの

- 機体名を偽った状態（`--machine` / `HARNESS_MACHINE` は試験用の逃げ道。
  人が意図して外す分には止められない）
- どの機体にも属さないパスの変更（役割分担は全ファイルを覆っていない）。
  `strict: true` にすると落とせる
- 確かめた方法: --self-test（担当外を名乗って design/ を変えたら落ちること）
"""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

#: 試験と、機体判定が効かない環境のための逃げ道
ENV_OVERRIDE = "HARNESS_MACHINE"


def detect_machine():
    """機体名を返す。判定できなければ None（**推測しない**）。

    machine-relay/SKILL.md の Step 1 と同じ方法。3台ともホームのパスも
    git のコミッタ名も同じなので、そこからは見分けられない。
    """
    forced = os.environ.get(ENV_OVERRIDE)
    if forced:
        return forced
    system = platform.system()
    if system == "Windows":
        return "Windows"
    if system != "Darwin":
        return None
    # **名前のまま起動しない。** Windows で .bat/.cmd が解決されないのと同じ形を
    # 道具の側でやらないため（この関数は Darwin でしか来ないが、規律を揃える）
    exe = shutil.which("scutil")
    if not exe:
        return None
    try:
        name = subprocess.run([exe, "--get", "ComputerName"],
                              capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    if not name:
        return None          # Mac なのに空 = 判定できていない。Windows と決めない
    low = name.lower()
    if "macbook" in low:
        return "MacBook Air"
    if "mini" in low:
        return "Mac mini"
    return None              # 不明。ユーザーに確認する（machine-relay と同じ）


#: shared に当たったときの担当。**全機体が担当**を意味する
SHARED = "（共有）"


def norm(p):
    """パスを比べられる形にする。

    `lstrip("./")` は**文字を剥がす**ので `.harness_log.jsonl` が
    `harness_log.jsonl` になっていた（2026-09-04 に直した）。
    """
    s = str(p).replace("\\", "/")
    while s.startswith("./"):
        s = s[2:]
    return s.rstrip("/")


def _under(target, own):
    """target が own 自身か、その下にあるか。**境界を見る。**

    素の `startswith` だと `design/` の宣言が `designs/x` にも当たる。
    """
    own = norm(own)
    if own == "":
        return True
    return target == own or target.startswith(own + "/")


def owner_of(path, conf):
    """path の担当を1つ返す。**最長一致。** shared に当たれば SHARED。

    **判定はここ1か所だけ。** 以前は `owns` が緩い前方一致（どちら向きでも）で
    別に持っており、同じパスに違う答えを返していた（#29）。
    """
    target, best, best_len = norm(path), None, -1
    for m, paths in conf.get("machines", {}).items():
        for own in paths:
            o = norm(own)
            if _under(target, o) and len(o) > best_len:
                best, best_len = m, len(o)
    for s in conf.get("shared", []):
        o = norm(s)
        if _under(target, o) and len(o) > best_len:
            best, best_len = SHARED, len(o)
    return best


def owns(machine, path, conf):
    """machine が path に責任を持つか。**owner_of と必ず同じ答えになる。**

    shared は**全機体が担当**とする。以前は shared を見ていなかったので、
    shared に結んだ段が全機体で飛んでいた（#40）。
    """
    holder = owner_of(path, conf)
    return holder == machine or holder == SHARED


def is_shared(path, conf):
    target = norm(path)
    return any(_under(target, s) for s in conf.get("shared", []))


def changed_files(root):
    """未コミットの変更 ＋ upstream に無いコミットの変更。"""
    out = set()

    def git(*args):
        try:
            r = subprocess.run(["git", "-C", str(root), *args],
                               capture_output=True, text=True, timeout=30)
            return r.stdout if r.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            return None

    # -uall: 未追跡はディレクトリに畳まず1ファイルずつ出す。畳まれると
    # 「lib/」のような担当の付かないパスになり、担当外の変更を見逃す
    status = git("status", "--porcelain", "-uall")
    if status is None:
        return None
    for line in status.splitlines():
        name = line[3:].strip()
        if " -> " in name:                      # rename
            name = name.split(" -> ", 1)[1]
        if name:
            out.add(name.strip('"'))

    base = _base_ref(git)
    if base:
        # **既定ブランチとの差**を見る。以前は @{u}（push した時点のリモート
        # ブランチ）と比べていたので、rebase やマージで取り込んだ**他機体の
        # コミット**が自分の変更として数えられ、push が止まった（#49・計5回）。
        diff = git("diff", "--name-only", f"{base}...HEAD")
        if diff:
            out.update(x.strip() for x in diff.splitlines() if x.strip())
    return out


def _base_ref(git):
    """自分のコミットだけを数えるための土台。**既定ブランチ**を探す。

    `origin/main...HEAD` は merge-base から HEAD までを見るので、
    既定ブランチを取り込んでも・rebase しても、**他機体のコミットは入らない。**
    """
    head = git("symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    if head and head.strip():
        return head.strip()
    for cand in ("origin/main", "origin/master"):
        if git("rev-parse", "--verify", "--quiet", cand):
            return cand
    up = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    return up.strip() if up and up.strip() else None


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="検査の段を、その失敗を起こせる機体に結び直す")
    ap.add_argument("--config", type=Path,
                    help="既定: <--root>/design/machine-scope.json。"
                         "--owns / --test-owns / --check には要る")
    ap.add_argument("--machine", help="機体名を明示する（試験用）")
    ap.add_argument("--whoami", action="store_true")
    ap.add_argument("--owns", metavar="PATH",
                    help="このパスを担当していれば -- の後のコマンドを実行する。"
                         "担当外なら理由を出して 0（段を通す）")
    ap.add_argument("--test-owns", metavar="PATH",
                    help="担当していれば 0・していなければ 3 を返す（shell の分岐用）。"
                         "--owns は『段を通す』ので、真偽の判定には使えない。"
                         "**set -e の下では if か || で受ける**（そのまま呼ぶと "
                         "3 でスクリプトごと死に、以降の検査が1本も走らない）")
    ap.add_argument("--check", action="store_true",
                    help="担当外のパスを変えていないか")
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("cmd", nargs=argparse.REMAINDER,
                    help="-- のあとに実行するコマンド")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    machine = args.machine or detect_machine()
    if args.whoami:
        print(machine or "不明")
        return 0 if machine else 2
    if not args.config:
        # **既定の場所を試す。** 以前は必ず落ちていたので、手で呼ぶと
        # 「引数が足りない」→「--config が要る」で2回失敗していた（#7）
        guess = args.root / "design" / "machine-scope.json"
        if guess.exists():
            args.config = guess
        else:
            # 他の設定エラーと揃えて **返す**（ap.error は SystemExit を投げるので、
            # 呼び出し側が終了コードで分岐できない）
            print(f"--config が要ります（--whoami / --self-test を除く）。\n"
                  f"  既定の場所を見ましたが在りませんでした: {guess}", file=sys.stderr)
            return 2

    try:
        conf = json.loads(args.config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"設定が読めません: {args.config}: {e}", file=sys.stderr)
        return 2

    known = list(conf.get("machines", {}))
    if not known:
        print(f"設定に machines がありません: {args.config}", file=sys.stderr)
        return 2
    if machine is None or machine not in known:
        # **不明なら飛ばさず落とす。** 知らない機体を素通りさせると、
        # 「担当外だから飛ばした」で全段が消える
        print(f"機体を判定できませんでした（検出: {machine or 'なし'}）。\n"
              f"  設定にある機体: {' / '.join(known)}\n"
              f"  判定できないまま段を飛ばすことはしません。"
              f"{ENV_OVERRIDE} で明示するか、設定に足してください。", file=sys.stderr)
        return 2

    if args.check:
        return do_check(machine, conf, args.root)

    if args.test_owns:
        if owns(machine, args.test_owns, conf):
            print(f"この機体（**{machine}**）は {args.test_owns} を担当しています。")
            return 0
        holder = owner_of(args.test_owns, conf) or "（設定に担当なし）"
        print(f"飛ばしました: この機体（**{machine}**）は {args.test_owns} を触りません。\n"
              f"  この段が守る失敗を起こせるのは {args.test_owns} を触る機体"
              f"（{holder}）だけです。\n"
              f"  対の検査: --check が「担当外のパスを変えていないか」を見ます。")
        return 3

    if args.owns:
        if owns(machine, args.owns, conf):
            cmd = [a for a in args.cmd if a != "--"]
            if not cmd:
                print(f"この機体（{machine}）は {args.owns} を担当しています。")
                return 0
            return subprocess.run(cmd).returncode
        holder = owner_of(args.owns, conf) or "（設定に担当なし）"
        # **黙って飛ばさない。** 機体名と理由を必ず出す
        print(f"飛ばしました: この機体（**{machine}**）は {args.owns} を触りません。\n"
              f"  この段が守る失敗を起こせるのは {args.owns} を触る機体"
              f"（{holder}）だけです。\n"
              f"  対の検査: --check が「担当外のパスを変えていないか」を見ます。")
        return 0

    ap.error("--whoami / --owns / --test-owns / --check のどれかが要ります")


def do_check(machine, conf, root):
    files = changed_files(root)
    if files is None:
        print(f"git の状態が読めません: {root}\n"
              f"  担当外の変更を確かめられないので通しません。", file=sys.stderr)
        return 2

    mine, others, unowned = [], [], []
    for f in sorted(files):
        if is_shared(f, conf):
            continue
        holder = owner_of(f, conf)
        if holder is None:
            unowned.append(f)
        elif holder == machine:
            mine.append(f)
        else:
            others.append((f, holder))

    print(f"機体の担当: **{machine}** / 変更 {len(files)}件"
          f"（担当内 {len(mine)} / 担当外 {len(others)} / 担当なし {len(unowned)}）")
    if unowned:
        print(f"  担当の宣言が無いパス（{len(unowned)}件）: "
              + " / ".join(unowned[:6]) + (" …" if len(unowned) > 6 else ""))
        if conf.get("strict"):
            print("\n担当の宣言が無いパスを変更しています（strict）:", file=sys.stderr)
            for f in unowned:
                print(f"  - {f}", file=sys.stderr)
            return 1
    if others:
        print(f"\n担当外のパスを変更しています（{machine}）:", file=sys.stderr)
        for f, holder in others:
            print(f"  - {f}（担当: {holder}）", file=sys.stderr)
        print(f"  役割の正本: ~/.claude/skills/machine-relay/references/worker.md\n"
              f"  意図した変更なら、その機体で作業し直すか、"
              f"machine-scope.json の担当を変えてください。", file=sys.stderr)
        return 1
    print("  OK: 担当外のパスは変更していません。")
    return 0


def self_test():
    import tempfile
    ok = True
    conf = {"machines": {"MacBook Air": ["lib/ui/", "design/"],
                         "Mac mini": ["ios/"],
                         "Windows": ["lib/data/", "scripts/"]},
            "shared": ["SESSION_LOG.md"]}

    def check(cond, msg):
        nonlocal ok
        if not cond:
            print(f"self-test NG: {msg}"); ok = False

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "c.json").write_text(json.dumps(conf), encoding="utf-8")
        C = ["--config", str(root / "c.json")]

        # 担当なら実行する
        rc = main(C + ["--machine", "MacBook Air", "--owns", "design/",
                       "--", sys.executable, "-c", "raise SystemExit(7)"])
        check(rc == 7, f"担当なのにコマンドを実行しなかった（{rc}）")

        # 担当外なら飛ばして 0（＝コマンドは走らない）
        rc = main(C + ["--machine", "Windows", "--owns", "design/",
                       "--", sys.executable, "-c", "raise SystemExit(7)"])
        check(rc == 0, f"担当外なのにコマンドが走った（{rc}）")

        # --test-owns は真偽を返す（--owns は段を通すので分岐に使えない）
        check(main(C + ["--machine", "MacBook Air", "--test-owns", "design/"]) == 0,
              "担当なのに --test-owns が 0 を返さない")
        check(main(C + ["--machine", "Windows", "--test-owns", "design/"]) == 3,
              "担当外なのに --test-owns が 3 を返さない")

        # 機体が不明なら**飛ばさず落ちる**（素通りさせない）
        rc = main(C + ["--machine", "知らない機体", "--owns", "design/"])
        check(rc == 2, f"不明な機体を素通りさせた（{rc}）")

        # --- 対の検査 ---
        subprocess.run(["git", "-C", str(root), "init", "-q"], capture_output=True)
        for p in ("design/x.json", "lib/data/y.dart", "SESSION_LOG.md"):
            (root / p).parent.mkdir(parents=True, exist_ok=True)
            (root / p).write_text("{}", encoding="utf-8")

        R = ["--root", str(root)]
        # Windows が design/ を変えている → 落ちる（この回の本体）
        rc = main(C + R + ["--machine", "Windows", "--check"])
        check(rc == 1, f"Windows が design/ を変えたのに落ちなかった（{rc}）")
        # MacBook Air なら design/ は担当内。lib/data/ は担当外なので落ちる
        rc = main(C + R + ["--machine", "MacBook Air", "--check"])
        check(rc == 1, f"MacBook Air が lib/data/ を変えたのに落ちなかった（{rc}）")
        # 担当内だけなら通る
        (root / "lib/data/y.dart").unlink()
        rc = main(C + R + ["--machine", "MacBook Air", "--check"])
        check(rc == 0, f"担当内だけなのに落ちた（{rc}）")
        # shared は誰が変えてもよい
        rc = main(C + R + ["--machine", "Mac mini", "--check"])
        check(rc == 1, "Mac mini が design/ を変えたのに落ちなかった")
        (root / "design/x.json").unlink()
        rc = main(C + R + ["--machine", "Mac mini", "--check"])
        check(rc == 0, "SESSION_LOG.md だけなのに落ちた（shared が効いていない）")

        # git が無い場所では落ちる（確かめられないまま通さない）
        with tempfile.TemporaryDirectory() as td2:
            rc = main(C + ["--root", str(Path(td2)), "--machine", "Windows", "--check"])
            check(rc in (1, 2), f"git 外なのに通した（{rc}）")

        # 環境変数の逃げ道が効く
        os.environ[ENV_OVERRIDE] = "Mac mini"
        try:
            check(detect_machine() == "Mac mini", f"{ENV_OVERRIDE} が効かない")
        finally:
            del os.environ[ENV_OVERRIDE]

    # ── #29: owns と owner_of が同じ答えを返す ──────────────────────────
    c2 = {"machines": {"MacBook Air": ["design/"],
                       "Windows": ["design/emulator_runs.json"],
                       "Mac mini": ["design/simulator_runs.json"]},
          "shared": ["SESSION_LOG.md", "docs/"]}
    for f in ("design/emulator_runs.json", "design/simulator_runs.json", "design/figma/x.json"):
        holder = owner_of(f, c2)
        for m in c2["machines"]:
            check(owns(m, f, c2) == (m == holder),
                  f"**{f} で owns({m}) と owner_of が食い違う**（owner={holder}）")
    check(owner_of("design/emulator_runs.json", c2) == "Windows", "最長一致になっていない")
    check(not owns("MacBook Air", "design/emulator_runs.json", c2),
          "**広い宣言を持つ機体が、上書きされたファイルまで担当と出る**")
    # 段を結ぶとき（範囲）も、担当外は False
    check(owns("MacBook Air", "design/", c2), "範囲の担当が False になった")
    check(not owns("Windows", "design/", c2),
          "**1ファイルしか持たない機体が design/ の段を担当と出る**")
    check(not owns("Windows", "design/figma/", c2), "design/figma/ でも担当と出る")

    # ── #40: shared は全機体が担当 ──────────────────────────────────────
    check(owner_of("SESSION_LOG.md", c2) == SHARED, "shared が担当なしのまま")
    for m in c2["machines"]:
        check(owns(m, "SESSION_LOG.md", c2),
              f"**shared に結んだ段が {m} で飛ぶ**")
        check(owns(m, "docs/a/b.md", c2), f"shared の下が {m} で飛ぶ")

    # ── 境界を見る（design/ が designs/ に当たらない）──────────────────
    check(owner_of("designs/x.json", c2) is None,
          "**design/ の宣言が designs/ にも当たっている**")
    check(norm(".harness_log.jsonl") == ".harness_log.jsonl",
          "**先頭のドットを剥がしている**（lstrip の取りこぼし）")

    # ── #49: 取り込んだ他機体のコミットを自分の変更と数えない ────────────
    import shutil
    td3 = tempfile.mkdtemp()
    try:
        root = Path(td3)
        def g(*a, cwd=root):
            return subprocess.run(["git", "-C", str(cwd), *a],
                                  capture_output=True, text=True)
        up = Path(td3 + "-up")
        g("init", "-q", "--bare", str(up), cwd=root.parent) if False else None
        subprocess.run(["git", "init", "-q", "--bare", str(up)], capture_output=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(root)], capture_output=True)
        g("config", "user.email", "t@t"); g("config", "user.name", "t")
        g("remote", "add", "origin", str(up))
        (root / "design").mkdir(); (root / "lib").mkdir()
        (root / "c.json").write_text(json.dumps(c2), encoding="utf-8")
        (root / "README.md").write_text("x", encoding="utf-8")
        g("add", "-A"); g("commit", "-qm", "init"); g("push", "-q", "origin", "main")

        # 他機体が main を進める（Windows 担当のファイル）
        (root / "design/emulator_runs.json").write_text("{}", encoding="utf-8")
        g("add", "-A"); g("commit", "-qm", "windows"); g("push", "-q", "origin", "main")

        # 自分は枝を切って、自分の担当だけ触る
        g("checkout", "-q", "-b", "mine", "HEAD~1")
        (root / "design").mkdir(exist_ok=True)   # git は空のディレクトリを持たない
        (root / "design/mine.json").write_text("{}", encoding="utf-8")
        g("add", "-A"); g("commit", "-qm", "mine")
        # **枝を push して upstream を作る。** これが無いと @{u} が引けず、
        # 古い実装でも素通りしてしまい、この検査が意味を持たない
        g("push", "-q", "-u", "origin", "mine")
        g("fetch", "-q", "origin")
        g("merge", "-q", "--no-edit", "origin/main")   # ← 他機体のコミットを取り込む

        C2 = ["--config", str(root / "c.json"), "--root", str(root)]
        rc = main(C2 + ["--machine", "MacBook Air", "--check"])
        check(rc == 0,
              f"**取り込んだ他機体のコミットを自分の変更と数えた（{rc}）**")

        # 本当に自分が担当外を変えたら、ちゃんと落ちる
        (root / "lib/x.dart").write_text("x", encoding="utf-8")
        g("add", "-A"); g("commit", "-qm", "trespass")
        c3 = dict(c2); c3["machines"] = dict(c2["machines"])
        c3["machines"]["Windows"] = ["design/emulator_runs.json", "lib/"]
        (root / "c.json").write_text(json.dumps(c3), encoding="utf-8")
        rc = main(C2 + ["--machine", "MacBook Air", "--check"])
        check(rc == 1, f"本当の越境を見逃した（{rc}）")
    finally:
        shutil.rmtree(td3, ignore_errors=True)
        shutil.rmtree(td3 + "-up", ignore_errors=True)

    # ── #7: --config を省くと既定の場所を試す ──────────────────────────
    td4 = tempfile.mkdtemp()
    try:
        root = Path(td4); (root / "design").mkdir(parents=True)
        (root / "design/machine-scope.json").write_text(json.dumps(c2), encoding="utf-8")
        rc = main(["--root", str(root), "--machine", "MacBook Air", "--test-owns", "design/"])
        check(rc == 0, f"**--config を省くと既定の場所を見ない（{rc}）**")
        rc = main(["--root", str(Path(tempfile.mkdtemp())), "--machine", "MacBook Air",
                   "--test-owns", "design/"])
        check(rc == 2, "既定の場所も無いのに落ちない")
    finally:
        shutil.rmtree(td4, ignore_errors=True)

    # ── #46: set -e の受け方が --help と docstring に書いてある ──────────
    check("set -e" in (__doc__ or ""), "**set -e の受け方が docstring に無い**")
    check("|| rc=$?" in (__doc__ or "") or "|| rc=" in (__doc__ or ""),
          "安全な受け方の例が docstring に無い")

    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
