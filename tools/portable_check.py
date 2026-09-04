#!/usr/bin/env python3
"""**Windows でだけ落ちる**書き方を、Mac / Linux から見つける（2026-09-04 新設）。

## なぜ要るか

**検査そのものが macOS でしか回っていない。** そのため「Windows でだけ落ちる」
バグが検査側に入り続ける。aub-familywalk では **3日で5件**見つかり、
**うち2件は「Windows 非互換を見つけるための検査」自身のバグ**だった。

Windows は3台のうち1台（データ・ロジック担当）。そこで `verify.sh` が
通らない間、その機体は「自分の変更が悪いのか道具が悪いのか」を毎回切り分ける。

## 何を見るか

| 見るもの | なぜ Windows で落ちるか |
|---|---|
| **出力の文字コード** | 日本語 Windows のコンソールは cp932。絵文字を `print` すると死ぬ |
| `open` / `read_text` / `write_text` に `encoding=` が無い | 既定が cp932 なので UTF-8 のファイルが読めない |
| 外部コマンドを**名前のまま**起動 | `.bat` / `.cmd` は `CreateProcess` が解決しない |
| `str(Path)` を `==` / `in` / `startswith` に使う | 区切りが `\\` になり、`/` 決め打ちと食い違う |

**1つ目は実際に回して確かめる**（静的には分からない。入力次第で出る）。
残り3つは静的に見る。

## 使い方

    portable_check.py                 # 全部
    portable_check.py --encoding      # 出力の文字コードだけ（回す。遅い）
    portable_check.py --style         # 書き方だけ（読むだけ。速い）

## 見つけられないもの

- `PATHEXT` がらみの細かい違い
- **実際の Windows でしか出ないもの**（cp932 のファイル名、パスの長さ制限）
  → これは Windows で回すしかない。この道具は**それまでの網**
"""
import argparse
import ast
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

HERE = Path(__file__).resolve().parent

#: 名前のまま呼んでよいもの。**理由が要る。**
NAME_OK = {
    "git": "Windows でも git.exe。CreateProcess が .exe を解決する",
    "node": "Windows でも node.exe",
    "python3": "ランナーが解決する。道具の中では sys.executable を使うこと",
    "python": "同上",
}
NON_CP932 = re.compile(r"[\U0001F300-\U0001FAFF←-⯿〰️]")


def _tools(root):
    return [f for f in sorted(root.glob("*.py")) if not f.name.startswith("_")]


def check_encoding(root, verbose=False):
    """cp932 の端末で全道具を回し、**出力で死ぬもの**を出す。"""
    env = {**os.environ, "PYTHONIOENCODING": "cp932"}
    env.pop("PYTHONUTF8", None)
    ng = []
    for f in _tools(root):
        try:
            r = subprocess.run([sys.executable, str(f), "--self-test"],
                               capture_output=True, text=True, errors="replace",
                               env=env, timeout=300)
        except subprocess.SubprocessError as e:
            ng.append((f.name, f"回せません: {e}")); continue
        err = r.stderr or ""
        if "UnicodeEncodeError" in err or "codec can't encode" in err:
            ng.append((f.name, "出力を cp932 に出せず**例外で死ぬ**"))
        elif verbose:
            print(f"  OK {f.name}")
    return ng


def check_style(root):
    """書き方を静的に見る。"""
    ng = []
    for f in _tools(root):
        try:
            src = f.read_text(encoding="utf-8")
            tree = ast.parse(src)
        except (OSError, SyntaxError) as e:
            ng.append((f.name, 0, f"読めません: {e}")); continue

        # _utf8 を import しているか（出力で死なないための土台）
        if "import _utf8" not in src:
            ng.append((f.name, 1, "**`import _utf8` が無い**。"
                                  "絵文字を出した瞬間に cp932 で死ぬ"))

        for node in ast.walk(tree):
            # encoding= の無い読み書き
            if isinstance(node, ast.Call):
                name = ""
                if isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                elif isinstance(node.func, ast.Name):
                    name = node.func.id
                if name in ("read_text", "write_text", "open"):
                    kw = {k.arg for k in node.keywords}
                    if "encoding" not in kw and "b" not in _mode_of(node):
                        ng.append((f.name, node.lineno,
                                   f"`{name}(` に `encoding=` が無い。"
                                   f"日本語 Windows の既定は cp932"))
                # 外部コマンドを名前のまま
                if name in ("run", "Popen", "check_output", "call"):
                    bad = _bare_command(node)
                    if bad:
                        ng.append((f.name, node.lineno,
                                   f"外部コマンド `{bad}` を名前のまま起動。"
                                   f"Windows の `.bat`/`.cmd` は解決されない"
                                   f"（`shutil.which` を通す）"))
    return ng


def _mode_of(node):
    for k in node.keywords:
        if k.arg == "mode" and isinstance(k.value, ast.Constant):
            return str(k.value.value)
    if node.args and isinstance(node.args[-1], ast.Constant):
        v = node.args[-1].value
        if isinstance(v, str) and set(v) <= set("rwxab+t"):
            return v
    return ""


def _bare_command(node):
    if not node.args:
        return None
    first = node.args[0]
    if not isinstance(first, ast.List) or not first.elts:
        return None
    head = first.elts[0]
    if not isinstance(head, ast.Constant) or not isinstance(head.value, str):
        return None            # sys.executable / 変数 → 解決済みとみなす
    name = head.value
    return None if name in NAME_OK else name


def main(argv=None):
    ap = argparse.ArgumentParser(description="Windows でだけ落ちる書き方を見つける")
    ap.add_argument("--root", type=Path, default=HERE)
    ap.add_argument("--encoding", action="store_true", help="出力の文字コードだけ")
    ap.add_argument("--style", action="store_true", help="書き方だけ")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()

    both = not (a.encoding or a.style)
    failed = 0
    tools = _tools(a.root)
    if not tools:
        print(f"道具が1本もありません: {a.root}\n"
              f"  **走査が空振りしています。**0件は「綺麗」ではありません。",
              file=sys.stderr)
        return 2

    if a.style or both:
        ng = check_style(a.root)
        print(f"書き方（道具 {len(tools)}本）: {len(ng)} 件")
        for name, line, why in ng:
            print(f"  {name}:{line}  {why}", file=sys.stderr)
        failed |= bool(ng)

    if a.encoding or both:
        ng = check_encoding(a.root, a.verbose)
        print(f"出力の文字コード（cp932 で {len(tools)}本を回した）: {len(ng)} 件")
        for name, why in ng:
            print(f"  {name}  {why}", file=sys.stderr)
        failed |= bool(ng)

    return 1 if failed else 0


def self_test():
    import shutil, tempfile
    ok = True
    def check(c, m):
        nonlocal ok
        if not c: ok = False; print(f"  NG: {m}")

    td = Path(tempfile.mkdtemp())
    try:
        shutil.copy(HERE / "_utf8.py", td / "_utf8.py")
        good = td / "good.py"
        good.write_text(
            "import sys\nfrom pathlib import Path\n"
            "sys.path.insert(0, str(Path(__file__).resolve().parent))\n"
            "import _utf8  # noqa\n"
            "import subprocess\n"
            "def f():\n"
            "    Path('x').read_text(encoding='utf-8')\n"
            "    subprocess.run([sys.executable, '-c', 'pass'])\n"
            "    subprocess.run(['git', 'status'])\n", encoding="utf-8")
        check(check_style(td) == [], f"綺麗な道具を咎めた: {check_style(td)}")

        # **encoding= が無いと落ちる**
        bad = td / "bad_enc.py"
        bad.write_text("import _utf8\nfrom pathlib import Path\n"
                       "Path('x').read_text()\n", encoding="utf-8")
        r = check_style(td)
        check(any("encoding=" in w for _, _, w in r),
              "**encoding= の無い read_text を見逃した**")
        bad.unlink()

        # **名前のままの外部コマンドが落ちる**
        bad = td / "bad_cmd.py"
        bad.write_text("import _utf8\nimport subprocess\n"
                       "subprocess.run(['flutter', 'build'])\n", encoding="utf-8")
        r = check_style(td)
        check(any("flutter" in w for _, _, w in r),
              "**名前のままの flutter を見逃した**")
        bad.unlink()

        # **_utf8 を import していないと落ちる**
        bad = td / "bad_utf8.py"
        bad.write_text("from pathlib import Path\n"
                       "Path('x').read_text(encoding='utf-8')\n", encoding="utf-8")
        r = check_style(td)
        check(any("_utf8" in w for _, _, w in r), "**import _utf8 の無い道具を見逃した**")
        bad.unlink()

        # バイナリ読みは咎めない
        b = td / "bin.py"
        b.write_text("import _utf8\nfrom pathlib import Path\n"
                     "open('x', 'rb')\n", encoding="utf-8")
        check(not any("encoding=" in w for _, _, w in check_style(td)),
              "バイナリ読みを咎めた")
        b.unlink()

        # **cp932 で死ぬ道具を捕まえる**
        emo = td / "emoji.py"
        emo.write_text("import sys\nfrom pathlib import Path\n"
                       "sys.path.insert(0, str(Path(__file__).resolve().parent))\n"
                       "print('⚙️_Systems')\n", encoding="utf-8")   # _utf8 を通さない
        ng = check_encoding(td)
        check(any(n == "emoji.py" for n, _ in ng),
              "**cp932 で死ぬ道具を見逃した**")
        # _utf8 を通せば死なない
        emo.write_text("import sys\nfrom pathlib import Path\n"
                       "sys.path.insert(0, str(Path(__file__).resolve().parent))\n"
                       "import _utf8\nprint('⚙️_Systems')\n", encoding="utf-8")
        ng = check_encoding(td)
        check(not any(n == "emoji.py" for n, _ in ng),
              "**_utf8 を通したのに死ぬと出た**")
        emo.unlink(); good.unlink()

        # **道具が1本も無いのに 0 で通さない**
        check(main(["--root", str(td), "--style"]) == 2,
              "**走査が空振りなのに通した**")
    finally:
        shutil.rmtree(td, ignore_errors=True)
    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
