#!/usr/bin/env python3
"""押す前の関門（pre-push）が、**この機体で実際に効いているか**を見る。

## 実害（2026-09-07・machine-relay の記録）

Windows が `aub-familywalk` へ **`verify.sh` が rc=1 のまま push できた。**
`.githooks/pre-push` はリポジトリに入っているのに、**その機体のクローンで
`core.hooksPath` が設定されていなかった**ため、フックが1度も呼ばれていなかった。

**`core.hooksPath` は `.git/config` に書く、クローンごとのローカル設定です。**
**リポジトリを配っても付いてきません。** 同じ人の同じ機体で、
**`flash` は止まり、`aub` は素通り**した。押された中身はたまたま無事だった。

## なぜ「たまたま」で済ませないか

関門は「効いていること」が前提の仕組みで、**効いていないことに気づく道が
どこにも無かった。** 検査は1つも無く、見つけたのは人が `git status` を見たとき。
**関門そのものが、検査されていない唯一の段だった。**

## 見るもの

- `core.hooksPath` が `.githooks` を指しているか
- `.githooks/pre-push` が在り、**実行できるか**（Windows は実行ビットが無くても
  動くので、そこは求めない）
- そのフックが `verify.sh` を呼んでいるか（**在るだけで中身が空**を弾く）

## 終了コード

    0  効いている
    1  効いていない（直し方を出す）
    2  **確かめられなかった**（git が無い・リポジトリの外・CI）
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401


def _git(args, cwd):
    exe = shutil.which("git")
    if not exe:
        return None
    try:
        r = subprocess.run([exe] + args, cwd=str(cwd), capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
    except OSError:
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def check(root: Path, want=".githooks", hook="pre-push"):
    """`(終了コード, 行の一覧)` を返す。"""
    out = []
    if os.environ.get("HARNESS_MACHINE") == "CI" or os.environ.get("CI"):
        return 0, ["押す前の関門: CI なので見ません（CI は push しません）"]

    inside = _git(["rev-parse", "--is-inside-work-tree"], root)
    if inside != "true":
        return 2, ["**git のリポジトリではありません。**"
                   "関門が効いているか確かめられないので落とします"]

    path = _git(["config", "core.hooksPath"], root)
    if path is None:
        return 1, [
            "**押す前の関門が、この機体で効いていません。**",
            f"  `core.hooksPath` が設定されていません（既定の `.git/hooks` を見ています）。",
            f"  リポジトリの `{want}/` は**呼ばれません**。",
            "  **`core.hooksPath` はクローンごとのローカル設定で、"
            "リポジトリを配っても付いてきません。**",
            f"  直し方: `git config core.hooksPath {want}`",
            "  実害（2026-09-07）: これが未設定のクローンから、"
            "`verify.sh` が赤いまま push が通りました",
        ]
    if path.rstrip("/") != want:
        return 1, [f"**関門の置き場が違います**: `core.hooksPath` = `{path}`"
                   f"（`{want}` のはず）",
                   f"  直し方: `git config core.hooksPath {want}`"]

    f = root / want / hook
    if not f.is_file():
        return 1, [f"**`{want}/{hook}` がありません。**"
                   f"`core.hooksPath` は設定されているのに、呼ぶ先が空です",
                   f"  元ファイル: `design/harness/ci/app-pre-push` を写してください"]

    # **在るだけでは通しません。** 中身が verify.sh を呼んでいるか
    try:
        body = f.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return 2, [f"**`{want}/{hook}` が読めません**: {e}"]
    if "verify.sh" not in body:
        return 1, [f"**`{want}/{hook}` が `verify.sh` を呼んでいません。**",
                   "  フックは在るのに何も検査していない状態です"]

    # 実行ビット。**Windows では意味が無いので落としません**（報せるだけ）
    note = ""
    if os.name != "nt" and not os.access(f, os.X_OK):
        note = "（**実行ビットがありません**。`chmod +x` が要ります）"
        return 1, [f"**`{want}/{hook}` に実行ビットがありません。**"
                   f"git は呼びません", f"  直し方: `chmod +x {want}/{hook}`"]

    out.append(f"押す前の関門: 効いています（`{path}/{hook}` が `verify.sh` を呼びます）{note}")
    return 0, out


def self_test():
    """**設定を外したら落ちること**が本体（妨害テスト）。"""
    import tempfile
    ok = True

    def ck(c, m):
        nonlocal ok
        if not c:
            ok = False
            print(f"  NG: {m}")

    exe = shutil.which("git")
    if not exe:
        print("git がありません。**確かめられないので 2 を返します**", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        subprocess.run([exe, "init", "-q"], cwd=str(root), check=True)

        # 1) 何も設定していない → **落ちる**
        rc, lines = check(root)
        ck(rc == 1, f"未設定なのに落ちない: {rc}")
        ck(any("core.hooksPath" in x for x in lines), "直し方を出していない")

        # 2) 設定したが呼ぶ先が無い → 落ちる
        subprocess.run([exe, "config", "core.hooksPath", ".githooks"],
                       cwd=str(root), check=True)
        rc, _ = check(root)
        ck(rc == 1, f"呼ぶ先が無いのに落ちない: {rc}")

        # 3) 在るが verify.sh を呼んでいない → **落ちる**（在るだけで通さない）
        hd = root / ".githooks"; hd.mkdir()
        hk = hd / "pre-push"
        hk.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        hk.chmod(0o755)
        rc, lines = check(root)
        ck(rc == 1, f"**何も検査しないフックを通した**: {rc}")
        ck(any("verify.sh" in x for x in lines), "理由を出していない")

        # 4) ちゃんと呼んでいる → 通る
        hk.write_text("#!/bin/sh\nsh design/verify.sh || exit 1\n", encoding="utf-8")
        hk.chmod(0o755)
        rc, _ = check(root)
        ck(rc == 0, f"効いているのに落ちる: {rc}")

        # 5) 実行ビットを外す → 落ちる（POSIX のみ）
        if os.name != "nt":
            hk.chmod(0o644)
            rc, _ = check(root)
            ck(rc == 1, f"**実行ビットが無いのに通した**: {rc}")
            hk.chmod(0o755)

        # 6) CI では見ない
        os.environ["HARNESS_MACHINE"] = "CI"
        subprocess.run([exe, "config", "--unset", "core.hooksPath"],
                       cwd=str(root), check=False)
        rc, _ = check(root)
        ck(rc == 0, f"CI なのに落ちる: {rc}")
        del os.environ["HARNESS_MACHINE"]

        # 7) git のリポジトリでなければ **2**
        with tempfile.TemporaryDirectory() as td2:
            rc, _ = check(Path(td2))
            ck(rc == 2, f"リポジトリの外なのに 2 を返さない: {rc}")

            # 8) **入口（main）まで通す。** `check` だけを見ていると、
            # 入口の落とす帰り道が**一度も走らない**（2026-09-07・
            # attack/mutation_test.py が「理由なしの素通り 2 件」として出した）
            import contextlib, io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = main(["--root", td2])
            ck(rc == 2, f"**入口がリポジトリの外で 2 を返さない**: {rc}")

        subprocess.run([exe, "config", "--unset", "core.hooksPath"],
                       cwd=str(root), check=False)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = main(["--root", str(root)])
        ck(rc == 1, f"**入口が未設定で 1 を返さない**: {rc}")
        subprocess.run([exe, "config", "core.hooksPath", ".githooks"],
                       cwd=str(root), check=True)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = main(["--root", str(root)])
        ck(rc == 0, f"**入口が効いているのに 0 を返さない**: {rc}")

    print("self-test: OK" if ok else "self-test: NG")
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="押す前の関門が、この機体で実際に効いているか")
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--hooks-path", default=".githooks")
    ap.add_argument("--hook", default="pre-push")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    rc, lines = check(a.root, a.hooks_path, a.hook)
    for x in lines:
        print(x, file=sys.stderr if rc else sys.stdout)
    # **落とす帰り道を式で書きます**（`return rc` にしない）。
    # 変異試験は「落ちる経路がソースに在るか」を見て測る対象を決めるので、
    # 変数で返すと**測れない道具**に分類され、素通りの分母から外れます
    # （2026-09-07・attack/mutation_test.py が実際にこの道具を弾きました）。
    if rc == 2:
        return 2
    if rc != 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
