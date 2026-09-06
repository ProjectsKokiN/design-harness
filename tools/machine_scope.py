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

実害（FlashEnglish・2026-09-03）: Mac mini と Windows が **2日間、
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
import re
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


def owner_of(path, conf, root=None):
    """path の担当を1つ返す。**最長一致。** shared に当たれば SHARED。

    **判定はここ1か所だけ。** 以前は `owns` が緩い前方一致（どちら向きでも）で
    別に持っており、同じパスに違う答えを返していた（#29）。

    **決定論的な生成物は、宣言より先に SHARED**（2026-09-06 ユーザー確定・issue #78）。
    `design/` を1つの機体の担当にすると、その下の生成物も自動的にその機体のものになり、
    **生成器を直した機体が、その直しを適用できない**という倒錯が起きる。
    実害（aub 2026-09-06）: 生成し直すと「担当外を変えた」、生成し直さないと
    「生成し直していない」で、**どちらを選んでも1段落ちる行き止まり**に入った。

    生成物かどうかは `generated.py` が**生成器の書いた印から導く**（一覧は宣言しない）。
    印が読めないファイル（消えた・壊れている）は生成物と見なさないので、
    **分からないものが勝手に共有にならない。**
    """
    if root is not None:
        try:
            from generated import is_generated
            f = Path(root) / norm(path)
            if f.is_file() and is_generated(f)[0]:
                return SHARED
        except Exception as e:  # noqa: BLE001  判定できないときは宣言に従う（安全側）
            # **黙って倒れない。** 判定器が無いと「生成物は共有」の規則が消え、
            # #78 の行き止まり（生成器を直した機体が適用できない）が無言で戻る
            print(f"注意: 生成物の判定器が使えません（{e}）。宣言どおりの担当に倒します。\n"
                  f"  **決定論的な生成物を共有にする規則が効いていません**"
                  f"（tools/generated.py を確かめてください）。", file=sys.stderr)
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


def owns(machine, path, conf, root=None):
    """machine が path に責任を持つか。**owner_of と必ず同じ答えになる。**

    shared は**全機体が担当**とする。以前は shared を見ていなかったので、
    shared に結んだ段が全機体で飛んでいた（#40）。
    """
    holder = owner_of(path, conf, root)
    return holder == machine or holder == SHARED


def is_shared(path, conf):
    target = norm(path)
    return any(_under(target, s) for s in conf.get("shared", []))


def changed_files(root):
    """未コミットの変更 ＋ upstream に無いコミットの変更。"""
    out = set()

    def git(*args, want_code=False):
        try:
            r = subprocess.run(["git", "-C", str(root), *args],
                               capture_output=True, text=True, timeout=30)
            if want_code:
                return r.returncode
            return r.stdout if r.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            return None

    # -uall: 未追跡はディレクトリに畳まず1ファイルずつ出す。畳まれると
    # 「lib/」のような担当の付かないパスになり、担当外の変更を見逃す
    status = git("status", "--porcelain", "-uall")
    if status is None:
        return None
    for line in status.splitlines():
        code, name = line[:2], line[3:].strip()
        if " -> " in name:                      # rename
            name = name.split(" -> ", 1)[1]
        name = name.strip('"')
        if not name:
            continue
        # **改行だけの差は変更と数えない。**
        #
        # core.autocrlf=true の作業ツリーは CRLF、リポジトリは LF。生成器が
        # LF で書き戻すと `git status` は「変更あり」と出すが、`git diff` は
        # 1行も差分を出さない（読むときに正規化されるため）。**中身は1バイトも
        # 違わない。** ここを数えると、Windows は生成器を回すたびに
        # 「担当外を変えた」で落ち、本物の NG が埋もれる（#41・aub で実測）。
        #
        # 未追跡（??）には差分の概念が無いので、そのまま数える。
        if code != "??" and _no_real_diff(git, name):
            continue
        out.add(name)

    base = _base_ref(git)
    if base:
        # **既定ブランチとの差**を見る。以前は @{u}（push した時点のリモート
        # ブランチ）と比べていたので、rebase やマージで取り込んだ**他機体の
        # コミット**が自分の変更として数えられ、push が止まった（#49・計5回）。
        diff = git("diff", "--name-only", f"{base}...HEAD")
        if diff:
            out.update(x.strip() for x in diff.splitlines() if x.strip())
    return out


def _no_real_diff(git, path):
    """`git status` は変更と言うが `git diff` は差分を出さない状態か。

    改行の正規化（CRLF ↔ LF）だけの差がこれに当たる。
    追跡外・判定できないときは **False**（数える側に倒す。見逃すより誤検知）。
    """
    for args in (("diff", "--quiet", "--", path),          # 作業ツリー vs 索引
                 ("diff", "--quiet", "--cached", "--", path)):  # 索引 vs HEAD
        r = git(*args, want_code=True)
        if r is None or r != 0:
            return False
    return True


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
    ap.add_argument("--handoff", action="store_true",
                    help="担当外の変更を担当機への申し送りとして切り出す")
    ap.add_argument("--apply", action="store_true",
                    help="--handoff で作業ツリーからも外す（**変更はパッチに残る**）")
    ap.add_argument("--check", action="store_true",
                    help="担当外のパスを変えていないか")
    ap.add_argument("--check-paths", action="store_true",
                    help="担当の宣言が実体を指しているか（#80。改名でずれると静かに担当なしになる）")
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
        return do_check(machine, conf, args.root, args.config)

    if args.check_paths:
        return do_check_paths(conf, args.root, args.config)

    if args.handoff:
        return do_handoff(machine, conf, args.root, args.apply)

    if args.test_owns:
        # **root を渡す。** 渡さないと「決定論的な生成物は SHARED」の規則が効かず、
        # --check と答えが食い違う（#29 と同じ形が別の入口に残っていた・2026-09-06）
        if owns(machine, args.test_owns, conf, args.root):
            print(f"この機体（**{machine}**）は {args.test_owns} を担当しています。")
            return 0
        holder = owner_of(args.test_owns, conf, args.root)
        if holder is None:
            return _no_owner(args.test_owns, args.config, known)
        holder = holder
        print(f"飛ばしました: この機体（**{machine}**）は {args.test_owns} を触りません。\n"
              f"  この段が守る失敗を起こせるのは {args.test_owns} を触る機体"
              f"（{holder}）だけです。\n"
              f"  対の検査: --check が「担当外のパスを変えていないか」を見ます。")
        return 3

    if args.owns:
        if owns(machine, args.owns, conf, args.root):
            cmd = [a for a in args.cmd if a != "--"]
            if not cmd:
                print(f"この機体（{machine}）は {args.owns} を担当しています。")
                return 0
            return subprocess.run(cmd).returncode
        holder = owner_of(args.owns, conf, args.root)
        if holder is None:
            return _no_owner(args.owns, args.config, known)
        # **黙って飛ばさない。** 機体名と理由を必ず出す
        print(f"飛ばしました: この機体（**{machine}**）は {args.owns} を触りません。\n"
              f"  この段が守る失敗を起こせるのは {args.owns} を触る機体"
              f"（{holder}）だけです。\n"
              f"  対の検査: --check が「担当外のパスを変えていないか」を見ます。")
        return 0

    ap.error("--whoami / --owns / --test-owns / --check のどれかが要ります")


def _no_owner(path, config, known):
    """**誰も担当していない段は落とす。** 飛ばすと、その段はどの機体でも走らない。

    黙って通すのは、このハーネスが繰り返し踏んできた
    「通ったと出るのに何も見ていない」そのもの（#37）。
    """
    print(f"**{path} の担当が設定にありません。**\n"
          f"  この段は**どの機体でも走りません。**飛ばさずに落とします。\n"
          f"  設定: {config}\n"
          f"  いまの機体: {' / '.join(known)}\n"
          f"  どの機体が {path} を触るかを machines に書くか、"
          f"全機体で走らせるなら shared に入れてください。", file=sys.stderr)
    return 2


def do_handoff(machine, conf, root, apply=False):
    """担当外の変更を、担当機への申し送りとして切り出す（2026-09-04・#13）。

    実害（FlashEnglish・2026-09-03）: **push できない組み合わせ**に入りました。
    テストの揺らぎの直しが担当外のファイルにあり、入れても出しても push
    できません。出口は3つのうち2つが塞がっていました。

    | 出口 | 可否 |
    |---|---|
    | `git push --no-verify` | **禁止**（中身を検査せずに送れる） |
    | その機体で作業し直す | その機体が別の場所にある。**今すぐは不可能** |
    | 担当を変える | 可能。ただし**役割の変更はユーザーの判断** |

    **3つ目の道**がこれです。差分をパッチとして残し、依頼の見出しを作り、
    `--apply` なら作業ツリーからも外します。

    道具の案内は行き止まりだけを示していました。**AI が毎回この手順を
    思いつく保証はありません**（実際、手でやってテストが落ちて振り出しに
    戻りました）。
    """
    import datetime
    files = changed_files(root)
    others = []
    for f in files:
        holder = owner_of(f, conf, root)
        if holder and holder != machine and holder != SHARED:
            others.append((f, holder))
    if not others:
        print("担当外の変更はありません。切り出すものがありません。")
        return 0

    out_dir = root / "design" / "handoff"
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    by_holder = {}
    for f, holder in others:
        by_holder.setdefault(holder, []).append(f)

    made = []
    for holder, paths in sorted(by_holder.items()):
        diff = subprocess.run(["git", "-C", str(root), "diff", "--", *paths],
                              capture_output=True, text=True)
        if diff.returncode != 0 or not diff.stdout.strip():
            print(f"  {holder}: 差分が取れません（新規ファイルは "
                  f"`git add -N` してください）: {' / '.join(paths)}",
                  file=sys.stderr)
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w.-]", "_", holder)
        pf = out_dir / f"{stamp}-{safe}.patch"
        pf.write_text(diff.stdout, encoding="utf-8")
        made.append((holder, pf, paths))

    if not made:
        return 1

    print("申し送りを作りました。**MACHINE_TASKS.md にこのまま貼ってください。**\n")
    for holder, pf, paths in made:
        rel = pf.relative_to(root)
        print(f"## {holder} へ: 担当外の変更を引き取る（{machine} が作った）\n")
        print(f"- 対象: {' / '.join(paths)}")
        print(f"- パッチ: `{rel}`")
        print(f"- 当て方: `git apply {rel}`")
        print(f"- なぜ: {machine} の関門を通すために要る変更ですが、"
              f"このパスは {holder} の担当です\n")

    if not apply:
        print("（下見です。作業ツリーからは外していません。"
              "外すなら --apply を付けてください）")
        return 0

    for holder, pf, paths in made:
        r = subprocess.run(["git", "-C", str(root), "checkout", "--", *paths],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(f"作業ツリーから外せませんでした: {' / '.join(paths)}\n"
                  f"  {r.stderr.strip()[:200]}", file=sys.stderr)
            return 1  # mutation-ok: git checkout の失敗。環境の経路（合成リポジトリで作れない）
    print(f"作業ツリーから外しました（{sum(len(p) for _, _, p in made)} ファイル）。"
          f"**変更はパッチに残っています。**")
    return 0


def ghost_paths(conf, root):
    """**宣言したのに実在しないパス**（2026-09-06 新設・#80）。

    `machines` と `shared` は手で書いたパス接頭辞の一覧です。**実在するかを誰も見ていません
    でした。** ディレクトリを1つ改名・移動しただけで、そのパスは静かに「担当なし」に落ち、
    担当分けの関門が**コードが動いた分だけ静かに面積を失います**。

    実測（2026-09-06）: planttalk は宣言17件のうち2件（`lib/data/` `lib/router/`）が実体を
    指しておらず、追跡256件のうち**124件が担当なし**でした。既定は `strict: false` なので
    注意が1行出るだけで exit 0 です。

    **これから作るものは宣言で通します。** 担当を先に決めてから書く運用は正当なので
    （`design/ios.json` が実際にそれ）、`$これから作る` に理由つきで載せます。

        "$これから作る": {"design/ios.json": "Mac mini がこれから測って書く（2026-09-06）"}

    戻り: ([(担当, パス)], 理由の無い宣言の一覧)
    """
    coming = conf.get("$これから作る") or {}
    no_reason = [k for k, v in coming.items() if not str(v).strip()]
    # **できあがったら宣言を消す。** `$これから作る` に載ったまま実体ができると、
    # その宣言は何も守らずに残ります（`platform_values_check` の「すでに正しいのに
    # 未対応の宣言が残っている」と同じ形。2026-09-06 に design/ios.json で実際に起きた）
    done = [k for k in coming if (Path(root) / str(k).rstrip("/")).exists()]
    out = []
    for m, paths in (conf.get("machines") or {}).items():
        for x in paths:
            rel = str(x).rstrip("/")
            if rel in coming or (Path(root) / rel).exists():
                continue
            out.append((m, str(x)))
    for x in (conf.get("shared") or []):
        rel = str(x).rstrip("/")
        if rel in coming or (Path(root) / rel).exists():
            continue
        out.append((SHARED, str(x)))
    return out, no_reason, done


def do_check_paths(conf, root, conf_path=''):
    """**宣言したパスが実体を指しているか**だけを見る（2026-09-06 新設・#80）。

    `--check`（担当外の変更を見る）とは別の段にしています。あちらは「何を変えたか」、
    こちらは「**宣言そのものが生きているか**」で、問いが違うためです。段を分けると
    `stage_check --stages` から見え、案件が外したときに「黙って落ちた段」として捕まります。
    """
    ghosts, no_reason, done = ghost_paths(conf, root)
    n = sum(len(v) for v in (conf.get("machines") or {}).values()) + len(conf.get("shared") or [])
    if not n:
        print(f"担当の宣言が1つもありません: {conf_path or '(設定)'}\n"
              f"  **0件は「担当分けなし」ではなく「見ていない」です。**", file=sys.stderr)
        return 2
    coming = conf.get("$これから作る") or {}
    if done and not ghosts and not no_reason:
        print(f"**できあがったのに `$これから作る` の宣言が残っています**（{len(done)}件）:",
              file=sys.stderr)
        for k in done:
            print(f"  - `{k}`（実体があります）", file=sys.stderr)
        print("  → 宣言を消してください。**残しても何も守りません**"
              "（宣言だけ残る化石・#80）", file=sys.stderr)
        return 1
    if not ghosts and not no_reason:
        print(f"担当の宣言: {n} 件、すべて実体を指しています"
              + (f"（これから作る {len(coming)} 件は理由つきで宣言済み）" if coming else ""))
        return 0
    print(f"**担当の宣言が実体を指していません**（{len(ghosts)}件 / 宣言 {n} 件）。\n"
          f"  改名・移動でパスがずれると、そこは静かに「担当なし」に落ちます。\n"
          f"  **担当分けの関門が、コードが動いた分だけ面積を失います**"
          f"（2026-09-06 実測: planttalk は宣言17件のうち2件が幽霊で、"
          f"追跡256件のうち124件が担当なしでした）:", file=sys.stderr)
    for m, x in ghosts:
        print(f"  - {m}: `{x}`", file=sys.stderr)
    for k in no_reason:
        print(f"  - `$これから作る` の `{k}` に理由がありません", file=sys.stderr)
    for k in done:
        print(f"  - `$これから作る` の `{k}` はできあがっています（宣言を消してください）",
              file=sys.stderr)
    print("  → 実体に合わせて直すか、これから作るものなら "
          "`$これから作る` に理由つきで書いてください", file=sys.stderr)
    return 1


def do_check(machine, conf, root, conf_path=''):
    files = changed_files(root)
    if files is None:
        print(f"git の状態が読めません: {root}\n"
              f"  担当外の変更を確かめられないので通しません。", file=sys.stderr)
        return 2

    ghosts, no_reason, done = ghost_paths(conf, root)
    coming = conf.get("$これから作る") or {}
    if coming:
        print(f"これから作るパスの宣言: {len(coming)} 件"
              + "".join(f"\n  {k}（{v}）" for k, v in sorted(coming.items())))

    mine, others, unowned = [], [], []
    for f in sorted(files):
        # **判定は owner_of だけ。** 以前はここで `is_shared()` を別に呼んでおり、
        # `owner_of` が SHARED を返すもの（生成物）を「担当: （共有）」と表示しながら
        # **担当外に数える**という食い違いが出た（2026-09-06。#29 と同じ形の再発）。
        holder = owner_of(f, conf, root)
        if holder == SHARED:
            continue
        if holder is None:
            unowned.append(f)
        elif holder == machine:
            mine.append(f)
        else:
            others.append((f, holder))

    print(f"機体の担当: **{machine}** / 変更 {len(files)}件"
          f"（担当内 {len(mine)} / 担当外 {len(others)} / 担当なし {len(unowned)}）")
    if ghosts or no_reason:
        # ここでは落とさない（担当外の変更を見る段の判定を変えない）。
        # **落とすのは独立した段**（`--check-paths`）。段にすると stage_check から見え、
        # 案件が外したときに「黙って落ちた段」として捕まる
        print(f"注意: 担当の宣言 {len(ghosts) + len(no_reason)} 件が実体を指していません"
              f"（`--check-paths` が落とします）: "
              + " / ".join(x for _, x in ghosts[:4]) + (" …" if len(ghosts) > 4 else ""))

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
              f"  出口は3つです:\n"
              f"    1. その機体で作業し直す\n"
              f"    2. machine-scope.json の担当を変える（**役割の変更は"
              f"ユーザーの判断**）\n"
              f"    3. **担当機への申し送りとして切り出す**:\n"
              f"       python3 <harness>/tools/machine_scope.py --config {conf_path} \\\n"
              f"           --handoff --root .        # 下見（パッチを書くだけ）\n"
              f"           --handoff --apply         # 作業ツリーからも外す\n"
              f"  **`git push --no-verify` は使いません。**"
              f"中身を検査せずに送れてしまうためです。", file=sys.stderr)
        return 1
    print("  OK: 担当外のパスは変更していません。")
    return 0


def shutil_rmtree(p):
    import shutil as _sh
    _sh.rmtree(p, ignore_errors=True)


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
        # 宣言したパスの**置き場だけ**作る（#80 の判定は実在を見る）。
        # **ファイルは置かない**——置くと担当外の変更として数えられ、この節の問いが変わる
        for d in ("lib/ui", "ios", "scripts"):
            (root / d).mkdir(parents=True, exist_ok=True)

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
    # **root ありでも owns と owner_of がそろうか**（生成物→SHARED の規則を通す経路）。
    # 2026-09-06: --owns / --test-owns が root を渡しておらず、--check と答えが違った
    with tempfile.TemporaryDirectory() as _td:
        _r = Path(_td)
        (_r / "design" / "figma").mkdir(parents=True)
        _gen = _r / "design" / "figma" / "notcaptured.json"
        _gen.write_text('{"$手で書き換えない": "gen_notcaptured.py が生成します"}',
                        encoding="utf-8")
        (_r / "design" / "hand.json").write_text('{"x": 1}', encoding="utf-8")
        _c = {"machines": {"MacBook Air": ["design/"], "Windows": ["lib/data/"]}}
        check(owner_of("design/figma/notcaptured.json", _c, _r) == SHARED,
              "**生成物が共有にならない**（root あり）")
        check(owner_of("design/hand.json", _c, _r) == "MacBook Air",
              "手で書くファイルまで共有にした")
        for _m in ("MacBook Air", "Windows"):
            _h = owner_of("design/figma/notcaptured.json", _c, _r)
            check(owns(_m, "design/figma/notcaptured.json", _c, _r) == (_h in (_m, SHARED)),
                  f"**root ありで owns({_m}) と owner_of が食い違う**")
        # root を渡さないと規則が効かない＝入口が root を渡し忘れると食い違う
        check(owner_of("design/figma/notcaptured.json", _c) == "MacBook Air",
              "root なしの答えが変わった（後方互換）")

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

    # ── #78: 決定論的な生成物は、宣言より先に共有（2026-09-06 ユーザー確定）──
    import tempfile as _tf
    _td = _tf.mkdtemp()
    try:
        _r = Path(_td)
        (_r / "design" / "figma").mkdir(parents=True)
        gen = _r / "design" / "figma" / "notcaptured.json"
        gen.write_text('{"$手で書き換えない": "gen が生成します"}', encoding="utf-8")
        hand = _r / "design" / "rules.json"
        hand.write_text('{"rules": []}', encoding="utf-8")

        # root を渡すと生成物は SHARED。渡さなければ宣言どおり（後方互換）
        check(owner_of("design/figma/notcaptured.json", c2, _r) == SHARED,
              "**生成物が共有になっていない**（生成器を直した機体が適用できなくなる）")
        check(owner_of("design/figma/notcaptured.json", c2) == "MacBook Air",
              "root を渡さないのに判定が変わった（後方互換が壊れている）")
        # 手で書くものは担当のまま
        check(owner_of("design/rules.json", c2, _r) == "MacBook Air",
              "**手で書くものまで共有にしている**")
        # 全機体が生成物を担当と見る（段が飛ばない）
        for m in c2["machines"]:
            check(owns(m, "design/figma/notcaptured.json", c2, _r),
                  f"生成物が {m} で担当外になる")
        # 存在しないファイルは宣言に従う（分からないものを共有にしない）
        check(owner_of("design/figma/no-such.json", c2, _r) == "MacBook Air",
              "**存在しないファイルを共有にした**")

        # **表示と集計が食い違わないこと**（2026-09-06 に実際に出た。#29 と同じ形）。
        # `--check` が別の判定（is_shared）を持っていたため、生成物を
        # 「担当: （共有）」と表示しながら**担当外に数えて**落としていた。
        import subprocess as _sp, io as _io, contextlib as _ctx
        _sp.run(["git", "-C", str(_r), "init", "-q"], check=True)
        _sp.run(["git", "-C", str(_r), "add", "-A"], check=True)
        _sp.run(["git", "-C", str(_r), "-c", "user.email=t@t", "-c", "user.name=t",
                 "commit", "-qm", "x"], check=True)
        gen.write_text('{"$手で書き換えない": "gen が生成します", "v": 2}', encoding="utf-8")
        _buf = _io.StringIO()
        with _ctx.redirect_stdout(_buf), _ctx.redirect_stderr(_buf):
            _rc = do_check("Mac mini", c2, _r)
        check(_rc == 0,
              f"**生成物だけを変えたのに担当外で落ちた（exit {_rc}）**"
              f"——表示と集計が食い違っている")
        check("担当外 0" in _buf.getvalue(),
              f"生成物が担当外に数えられている: {_buf.getvalue()[:200]}")
    finally:
        shutil_rmtree(_td)

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

    # ── #37: 誰も担当していない段は **落とす**（黙って飛ばさない）──────
    c6 = {"machines": {"A": ["lib/"], "B": ["ios/"]}, "shared": ["docs/"]}
    td6 = tempfile.mkdtemp()
    try:
        root = Path(td6); (root / "c.json").write_text(json.dumps(c6), encoding="utf-8")
        C6 = ["--config", str(root / "c.json")]
        rc = main(C6 + ["--machine", "A", "--owns", "design/figma/"])
        check(rc == 2, f"**誰も担当していない段を黙って通した（--owns / {rc}）**")
        rc = main(C6 + ["--machine", "A", "--test-owns", "design/figma/"])
        check(rc == 2, f"**誰も担当していない段を黙って通した（--test-owns / {rc}）**")
        # 担当がいるなら、担当外の機体は今までどおり飛ばす（0 / 3）
        check(main(C6 + ["--machine", "A", "--owns", "ios/"]) == 0, "担当外で落ちた（--owns）")
        check(main(C6 + ["--machine", "A", "--test-owns", "ios/"]) == 3, "担当外が 3 を返さない")
        # shared に入れれば全機体で走る
        check(main(C6 + ["--machine", "A", "--test-owns", "docs/"]) == 0, "shared が担当にならない")
    finally:
        shutil.rmtree(td6, ignore_errors=True)

    # ── #41: 改行だけの差を「担当外を変えた」と数えない ────────────────
    td5 = tempfile.mkdtemp()
    try:
        root = Path(td5)
        def g5(*a):
            return subprocess.run(["git", "-C", str(root), *a],
                                  capture_output=True, text=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(root)], capture_output=True)
        g5("config", "user.email", "t@t"); g5("config", "user.name", "t")
        # **作業ツリーは CRLF・リポジトリは LF**（Windows の core.autocrlf=true）
        g5("config", "core.autocrlf", "true")
        (root / "c.json").write_text(json.dumps(c2), encoding="utf-8")
        (root / "design").mkdir()
        gen = root / "design" / "gen.svg"
        gen.write_bytes(b"<svg>\r\n</svg>\r\n")
        g5("add", "-A"); g5("commit", "-qm", "init")
        # 生成器が **LF で書き戻す**（中身は1バイトも変わらない）
        gen.write_bytes(b"<svg>\n</svg>\n")

        st = g5("status", "--porcelain", "--", "design/gen.svg").stdout.strip()
        df = g5("diff", "--", "design/gen.svg").stdout.strip()
        if st and not df:          # この環境で CRLF の状況が作れたときだけ見る
            C5 = ["--config", str(root / "c.json"), "--root", str(root)]
            rc = main(C5 + ["--machine", "Windows", "--check"])
            check(rc == 0,
                  f"**改行だけの差を「担当外を変えた」と数えた（{rc}）**")
            # 中身が本当に変わったら、ちゃんと落ちる
            gen.write_bytes("<svg>ちがう</svg>\n".encode("utf-8"))
            rc = main(C5 + ["--machine", "Windows", "--check"])
            check(rc == 1, f"**本物の変更を見逃した（{rc}）**")
    finally:
        shutil.rmtree(td5, ignore_errors=True)

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

    # ─── #80: 宣言したパスが実在するか ─────────────────────────────
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "repo"; (root / "lib" / "ui").mkdir(parents=True)
        (root / "lib" / "ui" / "a.dart").write_text("1\n", encoding="utf-8")
        c = {"machines": {"A": ["lib/ui/"], "B": ["lib/data/"]}, "shared": ["docs/"]}
        g, nr, dn = ghost_paths(c, root)
        check(sorted(x for _, x in g) == ["docs/", "lib/data/"],
              f"**実在しない宣言を見つけられない**: {g}")
        check(nr == [], "理由の無い宣言が無いのに出た")
        # これから作るものは理由つきで通る
        c2 = dict(c, **{"$これから作る": {"lib/data": "B がこれから書く", "docs": "置き場を作る"}})
        check(ghost_paths(c2, root)[0] == [], f"理由つきの宣言を通さない: {ghost_paths(c2, root)[0]}")
        # 理由が空なら名指しする
        c3 = dict(c, **{"$これから作る": {"lib/data": "", "docs": "x"}})
        check(ghost_paths(c3, root)[1] == ["lib/data"], "理由の無い宣言を見逃した")
        # **できあがったら宣言を消す**（2026-09-06。design/ios.json で実際に起きた）
        (root / "lib" / "data").mkdir(parents=True, exist_ok=True)
        check(ghost_paths(c2, root)[2] == ["lib/data"], "**できあがった宣言を見つけられない**")
        import shutil as _sh2
        _sh2.rmtree(root / "lib" / "data")
        check(ghost_paths(c2, root)[2] == [], "実体が無いのにできあがったと言った")
        # **できあがった宣言だけが残る場合も落とす**（main の帰り道）
        (root / "lib" / "data").mkdir(parents=True, exist_ok=True)
        cfp2 = Path(td) / "c2.json"
        cfp2.write_text(json.dumps(dict(c2, **{"machines": {"A": ["lib/ui/"]},
                                               "shared": []}), ensure_ascii=False),
                        encoding="utf-8")
        subprocess.run(["git", "init", "-q", "-b", "main", str(root)], capture_output=True)
        check(main(["--config", str(cfp2), "--root", str(root), "--machine", "A",
                    "--check-paths"]) == 1,
              "**できあがった宣言だけが残っているのに通した**")
        _sh2.rmtree(root / "lib" / "data")
        # 実在するものは何も出さない
        c4 = {"machines": {"A": ["lib/ui/"]}}
        check(ghost_paths(c4, root)[0] == [], "実在する宣言を咎めた")
        # --check-paths の帰り道まで見る（--check は判定を変えない）
        subprocess.run(["git", "init", "-q", "-b", "main", str(root)], capture_output=True)
        cfp = Path(td) / "c.json"
        A = ["--config", str(cfp), "--root", str(root), "--machine", "A"]
        cfp.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
        check(main(A + ["--check-paths"]) == 1,
              "**実在しない宣言があるのに --check-paths が通した**")
        check(main(A + ["--check"]) == 0,
              "--check の判定まで変えた（担当外の変更を見る段は別の問い）")
        cfp.write_text(json.dumps(c2, ensure_ascii=False), encoding="utf-8")
        check(main(A + ["--check-paths"]) == 0, "理由つきの宣言があるのに落ちた")
        cfp.write_text(json.dumps(c3, ensure_ascii=False), encoding="utf-8")
        check(main(A + ["--check-paths"]) == 1, "理由の無い `$これから作る` を通した")
        cfp.write_text(json.dumps({"machines": {}}, ensure_ascii=False), encoding="utf-8")
        check(main(A + ["--check-paths"]) == 2,
              "宣言が0件なのに 2 で止まらなかった（0件は見ていない）")

    # ─── strict: 担当の宣言が無いパスを変えたら落ちる ───────────────
    # （変異試験 2026-09-05: `return 1` を `return 0` にしても自己検査が通っていた）
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "repo"; root.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(root)])
        (root / "lib").mkdir()
        (root / "lib" / "a.dart").write_text("1\n", encoding="utf-8")
        (root / "NOBODY.md").write_text("x\n", encoding="utf-8")
        cs = {"machines": {"A": ["lib/"]}, "strict": True}
        cfgp = Path(td) / "c.json"
        cfgp.write_text(json.dumps(cs), encoding="utf-8")
        CS = ["--config", str(cfgp), "--root", str(root), "--machine", "A", "--check"]
        rc = main(CS)
        check(rc == 1, f"strict なのに担当の宣言が無いパスの変更を通した（{rc}）")
        cs["strict"] = False
        cfgp.write_text(json.dumps(cs), encoding="utf-8")
        rc = main(CS)
        check(rc == 0, f"strict でないのに担当なしのパスで落ちた（{rc}）")

    # ─── #13: 担当外の変更を申し送りとして切り出す ─────────────────
    import contextlib as _ctx
    import io as _io
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        subprocess.run(["git", "init", "-q", "-b", "main", str(root)])
        for kv in (("user.email", "t@t"), ("user.name", "t")):
            subprocess.run(["git", "-C", str(root), "config", *kv])
        (root / "lib").mkdir()
        (root / "lib" / "mine.dart").write_text("1\n", encoding="utf-8")
        (root / "lib" / "theirs.dart").write_text("1\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "-A"])
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "1"])
        cf = {"machines": {"わたし": ["lib/mine.dart"],
                           "あいて": ["lib/theirs.dart"]}}

        def hand(*a):
            b = _io.StringIO()
            with _ctx.redirect_stdout(b), _ctx.redirect_stderr(b):
                rc = do_handoff("わたし", cf, root, *a)
            return rc, b.getvalue()

        rc, out = hand()
        if rc != 0 or "切り出すものがありません" not in out:
            print(f"self-test NG: 担当外が無いのに切り出した（{rc}）"); ok = False

        (root / "lib" / "theirs.dart").write_text("2\n", encoding="utf-8")
        rc, out = hand()
        if rc != 0 or "あいて へ" not in out or "git apply" not in out:
            print(f"self-test NG: 申し送りを作れない（{rc}）\n   {out[:300]}")
            ok = False
        pf = sorted((root / "design" / "handoff").glob("*.patch"))
        if not pf or "theirs.dart" not in pf[0].read_text(encoding="utf-8"):
            print("self-test NG: パッチに差分が入っていない"); ok = False
        # **下見では作業ツリーを触らない**
        if (root / "lib" / "theirs.dart").read_text(encoding="utf-8") != "2\n":
            print("self-test NG: 下見なのに作業ツリーを変えた"); ok = False

        rc, out = hand(True)
        if rc != 0 or "作業ツリーから外しました" not in out:
            print(f"self-test NG: --apply が効かない（{rc}）"); ok = False
        if (root / "lib" / "theirs.dart").read_text(encoding="utf-8") != "1\n":
            print("self-test NG: 作業ツリーから外れていない"); ok = False
        # **変更はパッチに残っている**（当て直せる）
        latest = sorted((root / "design" / "handoff").glob("*.patch"))[-1]
        r = subprocess.run(["git", "-C", str(root), "apply", str(latest)],
                           capture_output=True, text=True)
        if r.returncode != 0 or \
                (root / "lib" / "theirs.dart").read_text(encoding="utf-8") != "2\n":
            print(f"self-test NG: パッチを当て直せない: {r.stderr[:150]}"); ok = False

        # 差分が取れない（未追跡の新規ファイルだけ）→ 何も作れずに 1。
        # 「切り出すものが無い（0）」と区別する（変異試験 2026-09-05）
        subprocess.run(["git", "-C", str(root), "checkout", "--", "lib/theirs.dart"])
        (root / "lib" / "new.dart").write_text("n\n", encoding="utf-8")
        cf2 = {"machines": {"わたし": ["lib/mine.dart"],
                            "あいて": ["lib/theirs.dart", "lib/new.dart"]}}
        b = _io.StringIO()
        with _ctx.redirect_stdout(b), _ctx.redirect_stderr(b):
            rc = do_handoff("わたし", cf2, root)
        if rc != 1 or "git add -N" not in b.getvalue():
            print(f"self-test NG: 差分の取れない申し送りを 1 で返さない（{rc}）"
                  f"\n   {b.getvalue()[:200]}"); ok = False

    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
