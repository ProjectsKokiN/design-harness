#!/usr/bin/env python3
"""**統合検査の元ファイル（`ci/verify.sh.template`）を、作り物の案件で丸ごと回す**（2026-09-28）。

## なぜ要るか

元ファイルの段の判定と要約は**シェルで書かれていて、回す試験がありませんでした。**
「これから直す段」（#139・2026-09-24）は作り物で1回だけ確かめて入れましたが、
FlashEnglish が取り込んで次の 3 つが分かりました（2026-09-28）。

- 要約を最後の出口にだけ置いていたため、**途中で抜ける出口（quick）では出なかった**
- 予告を「名前が含まれるか」で見ていたため、**`テストの一部` と書くと `テスト` の段まで
  予告扱いになった**（予告した段は関門を通すので、書き間違いで本物の失敗が通る）
- 予告した名前に合う段が無いとき（ハーネスの中身の段は step を通らない）、**黙って空振りした**

PlantTalk の取り込み（同日）で、もう 1 つ分かりました。

- quick の出口は「まだ測れない段の宣言」を見ずに抜けていたため、**全体の検査なら宣言で
  覆われる段で、quick だけが 1 を返していた**（出口の扱いを finish にまとめた）

## 何をするか

元ファイルの `{{ }}` を作り物の呼び出しに置き換え、**道具を全部、決めた終了コードを
返すだけの作り物にした**ハーネス（本物の submodule）の上で、そのまま回します。
道具の中身は見ません。**段の判定・要約・出口**を見ます。

作り物の道具は、環境変数 `STUB_RC`（`名前=コード;名前=コード`）で終了コードを決めます。
名前は道具のファイル名（拡張子なし）か、`{{ }}` を置き換えた段の名前（`テスト`・`静的解析`）です。

## 終了コード

    0  全部の場合で、判定と要約が期待どおりだった
    1  どれかが違った
    2  **確かめられなかった**（git が無い・元ファイルを読めない・submodule を作れない）
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE.parent / "ci" / "verify.sh.template"

STUB = '''import os, sys
from pathlib import Path
key = sys.argv[1] if Path(__file__).stem == "fake_step" else Path(__file__).stem
for part in os.environ.get("STUB_RC", "").split(";"):
    k, _, v = part.partition("=")
    if k == key:
        sys.exit(int(v))
sys.exit(0)
'''

QUICK_STAGE = "設定の書式（鍵と型。走査対象が0件でも回る）"   # quick の出口より前の段
PIN_STAGE = "ハーネスの中身（記録されたピンと同じか）"


def build(base: Path, git: str):
    """作り物のハーネス（submodule）と案件を作り、案件の場所を返す。"""
    src = TEMPLATE.read_text(encoding="utf-8")
    tools = sorted(set(re.findall(r"\$HARNESS/tools/([A-Za-z0-9_]+)\.py", src)))
    up = base / "up"
    (up / "tools").mkdir(parents=True)
    (up / "engine").mkdir()
    for t in tools:
        (up / "tools" / f"{t}.py").write_text(STUB, encoding="utf-8")
    (up / "engine" / "design_check.py").write_text(STUB, encoding="utf-8")

    def g(*a, cwd):
        subprocess.run([git, "-c", "user.email=t@t", "-c", "user.name=t",
                        "-c", "commit.gpgsign=false", *a], cwd=str(cwd), check=True,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    g("init", "-q", "-b", "main", cwd=up)
    g("add", "-A", cwd=up)
    g("commit", "-qm", "stubs", cwd=up)

    prj = base / "prj"
    (prj / "design").mkdir(parents=True)
    g("init", "-q", "-b", "main", cwd=prj)
    add = subprocess.run([git, "-c", "protocol.file.allow=always", "submodule", "add", "-q",
                          str(up), "design/harness"], cwd=str(prj), capture_output=True,
                         text=True, encoding="utf-8", errors="replace")
    if add.returncode != 0:
        return None, f"submodule を作れませんでした: {add.stderr.strip()[:200]}"
    g("commit", "-qm", "sub", cwd=prj)

    body = src
    body = re.sub(r'(step "静的解析"\s+)\{\{[^}]*\}\}', r'\1"$PY" design/fake_step.py 静的解析', body)
    body = re.sub(r'(step "テスト"\s+)\{\{[^}]*\}\}', r'\1"$PY" design/fake_step.py テスト', body)
    body = re.sub(r"\{\{[^}]*\}\}", "x.json", body)
    (prj / "design" / "verify.sh").write_text(body, encoding="utf-8")
    (prj / "design" / "design_check.py").write_text(STUB, encoding="utf-8")
    (prj / "design" / "fake_step.py").write_text(STUB, encoding="utf-8")
    return prj, None


def run(prj: Path, home: Path, target=None, stub="", expected=None):
    env = {k: v for k, v in os.environ.items() if k != "HARNESS_EXPECTED_FAILURES"}
    env.update(HOME=str(home), FIGMA_TOKEN="x", PYTHON=sys.executable,
               PYTHONDONTWRITEBYTECODE="1", STUB_RC=stub)
    if expected is not None:
        env["HARNESS_EXPECTED_FAILURES"] = expected
    cmd = ["bash", "design/verify.sh"] + ([target] if target else [])
    r = subprocess.run(cmd, cwd=str(prj), env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300)
    return r.returncode, r.stdout + r.stderr


def main(argv=None):
    git = shutil.which("git")
    if not git or not shutil.which("bash"):
        print("git か bash がありません。**確かめられないので落とします**", file=sys.stderr)
        return 2
    if not TEMPLATE.is_file():
        print(f"元ファイルがありません: {TEMPLATE}", file=sys.stderr)
        return 2

    ok = True

    def ck(cond, msg, out=""):
        nonlocal ok
        if not cond:
            ok = False
            print(f"  NG: {msg}", file=sys.stderr)
            if out:
                print("    " + "\n    ".join(out.strip().splitlines()[-12:]), file=sys.stderr)

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        home = base / "home"
        home.mkdir()
        prj, why = build(base, git)
        if why:
            print(why, file=sys.stderr)
            return 2

        # 1) 何も落ちなければ通る（作り物の上で元ファイルが最後まで走ること自体の確かめ）
        rc, out = run(prj, home)
        ck(rc == 0 and "すべての検証を通過しました" in out,
           f"何も落ちていないのに通らない（rc={rc}）", out)
        ck("これから直す段" not in out, "予告していないのに要約が出た", out)

        # 2) 予告していない段が落ちれば 1
        rc, out = run(prj, home, stub="config_schema_check=1")
        ck(rc == 1, f"予告していない段が落ちたのに 1 でない（rc={rc}）", out)

        # 3) 予告した段が落ちれば、別の見出しにして要約に出す（関門は通す）
        rc, out = run(prj, home, stub="config_schema_check=1", expected=QUICK_STAGE)
        ck(rc == 0 and "これから直す段（予告どおり）" in out
           and "予告どおり落ちた段: 1 件" in out,
           f"予告した段の扱いが違う（rc={rc}）", out)

        # 4) **途中の出口（quick）でも要約が出る**（FlashEnglish の実測で直したところ）
        rc, out = run(prj, home, target="quick", stub="config_schema_check=1",
                      expected=QUICK_STAGE)
        ck(rc == 0 and "予告どおり落ちた段: 1 件" in out,
           f"quick の出口で要約が出ない（rc={rc}）", out)

        # 5) 予告したのに落ちなかった段を言う（古い予告を残さない）
        rc, out = run(prj, home, expected=QUICK_STAGE)
        ck(rc == 0 and "予告したのに落ちなかった段: 1 件" in out,
           f"落ちなかった予告を言わない（rc={rc}）", out)

        # 6) **名前は完全一致で見る。**`テストの一部` で `テスト` の段を予告扱いにしない
        rc, out = run(prj, home, stub="テスト=1", expected="テストの一部")
        ck(rc == 1, f"名前の一部が合うだけで予告扱いにした（rc={rc}）", out)
        ck("予告した名前に合う段が、この回にありません: 1 件" in out and "テストの一部" in out,
           "合う段の無い予告を言わない", out)

        # 7) ハーネスの中身の段は予告しても外れない（step を通らない・外せない段）。
        #    予告は「合う段が無い」と言う
        (prj / "design" / "harness" / "tools" / "config_schema_check.py").write_text(
            "import sys\nsys.exit(0)\n", encoding="utf-8")         # ハーネスを書き換える
        rc, out = run(prj, home, expected=PIN_STAGE)
        ck(rc == 1 and "ハーネスの中身が書き換えられています" in out,
           f"ハーネスを書き換えたのに、予告で通った（rc={rc}）", out)
        ck("予告した名前に合う段が、この回にありません" in out and PIN_STAGE in out,
           "ハーネスの中身の段への予告を、黙って空振りした", out)
        subprocess.run([git, "checkout", "--", "."], cwd=str(prj / "design" / "harness"),
                       check=True, capture_output=True)

        # 8) quick では走らない段の予告も「この回に無い」と言う
        rc, out = run(prj, home, target="quick", expected="テスト")
        ck(rc == 0 and "予告した名前に合う段が、この回にありません: 1 件" in out,
           f"quick で走らない段の予告を言わない（rc={rc}）", out)

        # 9) **quick でも「まだ測れない段の宣言」を見る**（全体の検査と同じ扱い）。
        #    PlantTalk の実測: 宣言済みの段で、quick だけが毎回 1 を返していた。
        #    宣言の中身は作り物の not_yet_check が決める（0 = 覆っている・1 = 覆っていない）
        (prj / "design" / "stages.json").write_text("{}", encoding="utf-8")
        rc, out = run(prj, home, target="quick", stub="config_schema_check=2")
        ck(rc == 0 and "宣言が覆っているので関門は通します" in out,
           f"quick で宣言を見ない（rc={rc}）", out)
        rc, out = run(prj, home, target="quick", stub="config_schema_check=2;not_yet_check=1")
        ck(rc == 1, f"quick で宣言が覆っていないのに通した（rc={rc}）", out)
        rc, out = run(prj, home, stub="config_schema_check=2")
        ck(rc == 0 and "宣言が覆っているので関門は通します" in out,
           f"全体の検査で宣言を見ない（rc={rc}）", out)
        (prj / "design" / "stages.json").unlink()

        # 10) quick で何も落ちなければ、全体の検査と取り違えない言い方で通す
        rc, out = run(prj, home, target="quick")
        ck(rc == 0 and "quick の段をすべて通過しました" in out
           and "すべての検証を通過しました" not in out,
           f"quick の通過を、全体の検査の通過と同じ言い方にした（rc={rc}）", out)

    print("verify_template_test:", "OK（12 通り）" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
