#!/usr/bin/env python3
"""**ハーネスの中身を守る段**が、本当に落ちるかを見る（design-harness #98）。

## なぜ、この段だけ道具ではなく素の shell なのか

**道具にすると、その道具を書き換えれば無効化できます。**
守る対象（submodule）の中に守り手を置くと、**守り手ごと書き換えられます**。
だから `ci/verify.sh.template` の中に **`git` だけを使う段**として直接書いてあり、
**案件のファイル（`design/verify.sh`）の側に住みます**。

## だから、ここで試験します

素の shell なので `--self-test` を持てません。**元ファイルからその段だけを
取り出して、作り物のリポジトリに当てます。**

## 実害（2026-09-09・aub-familywalk で実測）

`design/harness/tools/machine_scope.py` の `main` を `return 0` に書き換えて
`design/verify.sh` を回したところ、**結果は1文字も変わりませんでした**
（攻撃あり rc=1・NG2 / 攻撃なし rc=1・**同じ NG2**）。
親リポジトリは submodule の **SHA しか記録しない**ので、
**書き換えたまま検査を通して push できました。**

## 終了コード

    0  4つの攻撃すべてで落ち、綺麗なときは通った
    1  どれかが素通りした
    2  **確かめられなかった**（git が無い・段を取り出せない）
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE.parent / "ci" / "verify.sh.template"
BEGIN = "# --- ハーネスの中身が、記録されたピンと一致しているか"


def extract_guard(template: Path):
    """元ファイルから、その段だけを取り出す。"""
    if not template.is_file():
        return None, f"元ファイルがありません: {template}"
    src = template.read_text(encoding="utf-8")
    i = src.find(BEGIN)
    if i < 0:
        return None, ("**元ファイルにハーネスの中身を見る段がありません。**"
                      f"目印: `{BEGIN}`")
    # `if [ -e design/harness/.git ]; then` から、対応する `fi` の次の行まで
    m = re.search(r"\nfi\n", src[i:])
    if not m:
        return None, "段の終わりを見つけられません"
    return src[i:i + m.end()], None


def run_guard(guard: str, cwd: Path):
    """段を1つだけ回して、終了コードを返す。"""
    sh = "FAILED=0\n" + guard + "\nexit $FAILED\n"
    f = cwd / ".guard-test.sh"
    f.write_text(sh, encoding="utf-8")
    try:
        r = subprocess.run(["bash", str(f)], cwd=str(cwd), capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        return r.returncode, (r.stdout + r.stderr)
    finally:
        f.unlink(missing_ok=True)


def main(argv=None):
    exe = shutil.which("git")
    if not exe:
        print("git がありません。**確かめられないので落とします**", file=sys.stderr)
        return 2
    guard, why = extract_guard(TEMPLATE)
    if why:
        print(why, file=sys.stderr)
        return 2

    ok = True

    def ck(c, m):
        nonlocal ok
        if not c:
            ok = False
            print(f"  NG: {m}", file=sys.stderr)

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        # 上流にするリポジトリ（submodule の中身）
        up = base / "up"; up.mkdir()
        subprocess.run([exe, "init", "-q", "-b", "main"], cwd=str(up), check=True)
        (up / "tools").mkdir()
        (up / "tools" / "a.py").write_text("print(1)\n", encoding="utf-8")
        for c in (["config", "user.email", "t@t"], ["config", "user.name", "t"],
                  ["add", "-A"], ["commit", "-qm", "one"]):
            subprocess.run([exe] + c, cwd=str(up), check=True)
        (up / "tools" / "b.py").write_text("print(2)\n", encoding="utf-8")
        subprocess.run([exe, "add", "-A"], cwd=str(up), check=True)
        subprocess.run([exe, "commit", "-qm", "two"], cwd=str(up), check=True)
        older = subprocess.run([exe, "rev-parse", "HEAD~1"], cwd=str(up),
                               capture_output=True, text=True).stdout.strip()

        # 案件
        prj = base / "prj"; prj.mkdir()
        subprocess.run([exe, "init", "-q", "-b", "main"], cwd=str(prj), check=True)
        for c in (["config", "user.email", "t@t"], ["config", "user.name", "t"]):
            subprocess.run([exe] + c, cwd=str(prj), check=True)
        (prj / "design").mkdir()
        add = subprocess.run(
            [exe, "-c", "protocol.file.allow=always", "submodule", "add", "-q",
             str(up), "design/harness"], cwd=str(prj),
            capture_output=True, text=True)
        if add.returncode != 0:
            print("submodule を作れませんでした（この環境では確かめられません）:\n"
                  f"  {add.stderr.strip()[:200]}", file=sys.stderr)
            return 2
        subprocess.run([exe, "commit", "-qm", "add sub"], cwd=str(prj), check=True)

        sub = prj / "design" / "harness"

        # 1) 綺麗なら通る
        rc, out = run_guard(guard, prj)
        ck(rc == 0, f"綺麗なのに落ちた: {rc}\n{out}")

        # 2) **道具を書き換えたら落ちる**（ここが本体）
        (sub / "tools" / "a.py").write_text("print(999)\n", encoding="utf-8")
        rc, out = run_guard(guard, prj)
        ck(rc != 0, "**書き換えを見逃した**")
        ck("a.py" in out, f"どのファイルかを出していない:\n{out}")
        subprocess.run([exe, "checkout", "--", "."], cwd=str(sub), check=True)

        # 3) **道具を1本足したら落ちる**（未追跡）
        (sub / "tools" / "backdoor.py").write_text("pass\n", encoding="utf-8")
        rc, out = run_guard(guard, prj)
        ck(rc != 0, "**未追跡のファイルを見逃した**")
        ck("backdoor.py" in out, f"どのファイルかを出していない:\n{out}")
        (sub / "tools" / "backdoor.py").unlink()

        # 4) **違うコミットを指していたら落ちる**
        subprocess.run([exe, "checkout", "-q", older], cwd=str(sub), check=True)
        rc, out = run_guard(guard, prj)
        ck(rc != 0, "**違うコミットを見逃した**")
        ck(older[:8] in out, f"どのコミットかを出していない:\n{out}")
        subprocess.run([exe, "checkout", "-q", "main"], cwd=str(sub), check=True)

        # 5) 戻したら通る
        rc, out = run_guard(guard, prj)
        ck(rc == 0, f"戻したのに落ちた: {rc}\n{out}")

        # 6) **submodule を取り込んでいなければ落ちる**（`0 件` にしない）
        for p in sorted(sub.rglob("*"), reverse=True):
            p.unlink() if p.is_file() else p.rmdir()
        rc, out = run_guard(guard, prj)
        ck(rc != 0, "**submodule が空なのに通した**")

    print("engine_clean_test: OK" if ok else "engine_clean_test: NG",
          file=sys.stderr if not ok else sys.stdout)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
