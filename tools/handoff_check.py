#!/usr/bin/env python3
"""**引き継ぎの記録（セッションログ）が、いまの作業から離れていないか**を見る（2026-09-15 新設・#114）。

## なぜ要るか

**次のマシンが読むのは `SESSION_LOG.md` です。** 先頭のエントリが古いと、
そこから間違いが始まります。

aub-familywalk の実害（2026-08-29）: 先頭のエントリが「verify.sh は 12 段・
テスト 149 件」と書いたまま、**その後の 64 コミットが1行も入っていませんでした**
（そのとき実際は 26 段・604 件）。

## なぜ共有層に置くか

**この検査はハーネスに無く、案件ごとに実装がバラバラでした**（2026-09-11 の実測）。

| 案件 | 実装 |
|---|---|
| aub-familywalk | Python（`design/gen/session_log_check.py`） |
| FlashEnglish | Dart（`test/design/session_log_test.dart`） |
| PlantTalk | **1つも無し** |

PlantTalk では書式がもともと文書化されていたのに機械で見ておらず、
**書いたエントリが書式を外しても誰も気づきませんでした**。
aub の実装を写して入れましたが、**それで実装が3案件に複製されました**
（`design_check.py` が5案件に複製されて 515 行乖離した件と同じ形です）。

**だからここに置き、案件側は書式の宣言だけを持ちます。**

## 何を見るか

1. 先頭のエントリに、**宣言した節**があるか
2. 先頭のエントリに、**数は時点のものだと断る一文**があるか
   （散文の数は必ず古くなります。読む人に「いまの数は回して見る」と伝える）
3. **最後にログを直してから、コミットを重ねすぎていないか**

**中身を読んで判断しません。** 書いてあるかどうかだけを見ます。

## 宣言（案件側）

    {
      "$これは何": "引き継ぎの記録の書式。design-harness/tools/handoff_check.py が読む",
      "ログ": "SESSION_LOG.md",
      "要る節": ["### 作業概要", "### 途中・引き継ぎ"],
      "数の断り": "`./design/verify.sh` を回して見てください",
      "重ねてよいコミット数": 30
    }

## 使い方

    python3 tools/handoff_check.py --config design/handoff.json --root .
    python3 tools/handoff_check.py --self-test

終了コード: 0 = 確かめて合格 / 1 = 確かめて違反 / **2 = 確かめられなかった**
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

#: 宣言に要る欄。**足りなければ 2**（確かめられなかった）
NEEDED = ("ログ", "要る節", "数の断り")


def _git(root, *args):
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=30)
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def head_entry(text):
    """先頭のエントリ（最初の `## ` から次の `## ` まで）。"""
    m = list(re.finditer(r"^## ", text, re.M))
    if not m:
        return None
    end = m[1].start() if len(m) > 1 else len(text)
    return text[m[0].start():end]


def check(conf, root):
    """`(見つかったもの, 重ねたコミット数)`。呼ぶ側が終了コードを決める。"""
    log = Path(root) / conf["ログ"]
    if not log.exists():
        return [f"{conf['ログ']} がありません"], None
    text = log.read_text(encoding="utf-8")

    ng = []
    head = head_entry(text)
    if head is None:
        ng.append("エントリが1つもありません")
        head = ""
    for k in conf["要る節"]:
        if k not in head:
            ng.append(f"先頭のエントリに「{k}」がありません")
    danri = conf["数の断り"]
    if danri and danri not in head:
        ng.append(f"先頭のエントリに、**数は時点のものだと断る一文**が"
                  f"ありません（「{danri}」を含める）。散文の数は必ず古くなります")

    # 最後にログを直してから、いくつコミットを重ねたか
    kazu = None
    last = _git(root, "log", "--format=%H", "-1", "--", conf["ログ"])
    if last is not None:
        last = last.strip()
        if last:
            n = _git(root, "rev-list", "--count", f"{last}..HEAD")
            kazu = int((n or "0").strip() or 0)
        else:
            kazu = 0
        limit = conf.get("重ねてよいコミット数")
        if isinstance(limit, int) and kazu > limit:
            ng.append(f"ログを直さずに {kazu} コミット重ねています（上限 {limit}）。"
                      f"**次のマシンが読むのはこのファイルです**")
    return ng, kazu


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=Path("design/handoff.json"))
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()

    if not args.config.exists():
        # **宣言が無いのを「書式が無い」と読ませない。** 案件が書式を持たないなら、
        # それは検査の対象が無いのではなく**まだ決めていない**という意味
        print(f"引き継ぎの書式の宣言がありません: {args.config}\n"
              f"  **書式を決めていないのか、宣言を置き忘れたのかが区別できません。**\n"
              f"  次の形で置いてください（道具の docstring に例があります）:\n"
              f'    {{"ログ": "SESSION_LOG.md", "要る節": ["### 作業概要"], '
              f'"数の断り": "…"}}', file=sys.stderr)
        return 2
    try:
        conf = json.loads(args.config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"宣言が読めません: {args.config}: {e}", file=sys.stderr)
        return 2
    lack = [k for k in NEEDED if k not in conf]
    if lack:
        print(f"宣言に {' / '.join(lack)} がありません: {args.config}\n"
              f"  **足りない欄を既定で埋めません。**案件ごとに違う値なので、"
              f"埋めると黙って別の書式を見ることになります", file=sys.stderr)
        return 2
    if not conf["要る節"]:
        print(f"`要る節` が空です: {args.config}\n"
              f"  **0 件は「節が要らない」ではなく「見ていない」です。**", file=sys.stderr)
        return 2

    ng, kazu = check(conf, args.root)
    if ng:
        print("引き継ぎの記録が離れています:", file=sys.stderr)
        for x in ng:
            print(f"  - {x}", file=sys.stderr)
        return 1
    tail = f"・最後に直してから {kazu} コミット" if kazu is not None else "・重ねた数は数えられませんでした"
    print(f"引き継ぎの記録: 通った（先頭のエントリに要る節 {len(conf['要る節'])} 件あり{tail}）")
    return 0


def self_test():
    import contextlib
    import io
    import os
    import tempfile
    ok = True

    def chk(cond, msg):
        nonlocal ok
        if not cond:
            print(f"self-test NG: {msg}")
            ok = False

    CONF = {"ログ": "SESSION_LOG.md",
            "要る節": ["### 作業概要", "### 途中・引き継ぎ"],
            "数の断り": "回して見てください",
            "重ねてよいコミット数": 30}
    GOOD = ("## 2026-09-15 セッションログ（機体 / 役割）— 何かした\n\n"
            "### 作業概要\nした\n\n### 途中・引き継ぎ\nなし\n\n"
            "数はそのときのものです。いまの数は回して見てください。\n\n"
            "## 2026-09-14 セッションログ（機体 / 役割）— 前のもの\n\n古い\n")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        cfg = root / "handoff.json"
        log = root / "SESSION_LOG.md"
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t")
        subprocess.run(["git", "-C", str(root), "init", "-q", "-b", "main"],
                       capture_output=True, env=env)

        def run(*extra):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = main(["--config", str(cfg), "--root", str(root), *extra])
            return rc, buf.getvalue()

        cfg.write_text(json.dumps(CONF, ensure_ascii=False), encoding="utf-8")
        log.write_text(GOOD, encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True, env=env)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "x"],
                       capture_output=True, env=env)
        rc, out = run()
        chk(rc == 0, f"通るはずの記録で落ちた（{rc}）: {out[:200]}")

        # 要る節が欠けたら落ちる
        log.write_text(GOOD.replace("### 途中・引き継ぎ\nなし\n\n", ""), encoding="utf-8")
        rc, out = run()
        chk(rc == 1 and "途中・引き継ぎ" in out, f"節の欠けを見逃した（{rc}）")

        # **2番目のエントリに在っても駄目**（見るのは先頭だけ）
        log.write_text("## 新しい\n\n中身だけ\n\n" + GOOD, encoding="utf-8")
        rc, out = run()
        chk(rc == 1, f"先頭ではなく後ろのエントリで通した（{rc}）")

        # 数の断りが無ければ落ちる
        log.write_text(GOOD.replace("いまの数は回して見てください。", "いまの数は 30 件です。"),
                       encoding="utf-8")
        rc, out = run()
        chk(rc == 1 and "時点のもの" in out, f"数の断りの欠けを見逃した（{rc}）")

        # ログを直さずに重ねたら落ちる
        log.write_text(GOOD, encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True, env=env)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "log"],
                       capture_output=True, env=env)
        for i in range(3):
            (root / f"f{i}.txt").write_text("x", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True, env=env)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", f"c{i}"],
                           capture_output=True, env=env)
        cfg.write_text(json.dumps({**CONF, "重ねてよいコミット数": 2}, ensure_ascii=False),
                       encoding="utf-8")
        rc, out = run()
        chk(rc == 1 and "コミット重ねて" in out, f"重ねすぎを見逃した（{rc}）: {out[:200]}")
        cfg.write_text(json.dumps(CONF, ensure_ascii=False), encoding="utf-8")
        rc, _ = run()
        chk(rc == 0, f"上限の中なのに落ちた（{rc}）")

        # ─── **確かめられなかった**（2）を 1 と混ぜない ────────────────────
        cfg.unlink()
        rc, out = run()
        chk(rc == 2 and "区別できません" in out, f"宣言が無いのに {rc} を返した")
        cfg.write_text("{", encoding="utf-8")
        rc, _ = run()
        chk(rc == 2, f"壊れた宣言で {rc} を返した（2 であるべき）")
        cfg.write_text(json.dumps({"ログ": "SESSION_LOG.md"}, ensure_ascii=False),
                       encoding="utf-8")
        rc, out = run()
        chk(rc == 2 and "要る節" in out, f"欄が足りないのに {rc} を返した")
        cfg.write_text(json.dumps({**CONF, "要る節": []}, ensure_ascii=False),
                       encoding="utf-8")
        rc, out = run()
        chk(rc == 2 and "見ていない" in out, f"`要る節` が空なのに {rc} を返した")
        cfg.write_text(json.dumps(CONF, ensure_ascii=False), encoding="utf-8")
        log.unlink()
        rc, out = run()
        chk(rc == 1 and "がありません" in out, f"ログが無いのに {rc} を返した")

    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
