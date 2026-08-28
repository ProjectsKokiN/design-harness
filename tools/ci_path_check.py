#!/usr/bin/env python3
"""CI（workflow の YAML）が参照するファイルパスが実在するかを見る。

414 の実害（2026-08-28）: verify.yml が `harness/tools/staleness_check.py` を
参照する形で書かれていたのに、ローカルの判断で submodule を見送っており、
**CI が参照するパスが存在しない構成**になっていた。push して CI が落ちるまで
誰も気づけない状態は、関門を入れた意味を薄める。

使い方（リポジトリのルートで）:
    python3 tools/ci_path_check.py [--workflows .github/workflows]

見るもの・見ないもの:
  捕まえるもの: YAML の run / with に書かれた**変数を含まないパス**で、
                リポジトリ内に実在しないもの
  捕まえないもの: `$ds/check_flutter_gaps.py` のような**変数を含むパス**
                （シェル変数は解決できず誤検出になるためスキップする。
                 414 の実測: `for ds in */` の展開を解決できず誤検出した）、
                clone してから使うパス（/tmp 等リポジトリ外）
  確かめた方法: attack/engine_attack_test.py ではなく本ファイル末尾の
                self-test（--self-test で合成 YAML に対して落ちる/通るを確認）
"""

import argparse
import re
import sys
from pathlib import Path

#: パスらしい文字列。拡張子つきの相対パスだけを拾う（コマンド名や URL は拾わない）
PATH_RX = re.compile(
    r"(?<![\w/$])((?:[\w.-]+/)+[\w.-]+\.(?:py|sh|json|ya?ml|js|mjs|dart|md|txt))\b")


def paths_in(yml_text):
    out = []
    for line in yml_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "$" in line:      # 変数を含む行はスキップ（解決できない）
            continue
        if "http://" in line or "https://" in line:
            line = re.sub(r"https?://\S+", "", line)
        for m in PATH_RX.finditer(line):
            p = m.group(1)
            if p.startswith(("tmp/", "var/", "usr/", "opt/", "home/")):
                continue
            out.append(p)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="workflow の参照パスの実在検査")
    ap.add_argument("--workflows", type=Path, default=Path(".github/workflows"))
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    if not args.workflows.exists():
        print(f"workflow がありません: {args.workflows}（検査対象なし）")
        return 0

    missing, checked = [], 0
    for yml in sorted(args.workflows.glob("*.yml")) + sorted(args.workflows.glob("*.yaml")):
        for p in paths_in(yml.read_text(encoding="utf-8")):
            checked += 1
            if not (args.root / p).exists():
                missing.append(f"  {yml.name}: {p}")
    if checked == 0:
        print("注意: 検査できたパスが0件です（全部が変数入り、またはパスが無い）")
        return 0
    if missing:
        print("CI が参照するパスが実在しません（push すると CI が落ちます）:",
              file=sys.stderr)
        print("\n".join(sorted(set(missing))), file=sys.stderr)
        return 1
    print(f"CI の参照パス {checked} 件、すべて実在します。")
    return 0


def self_test():
    """この検査自身の妨害テスト（落ちるケースを1つ持つ）。"""
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        wf = root / ".github/workflows"
        wf.mkdir(parents=True)
        (root / "tools").mkdir()
        (root / "tools/real.py").write_text("", encoding="utf-8")
        (wf / "a.yml").write_text(
            "jobs:\n  a:\n    steps:\n"
            "      - run: python3 tools/real.py\n"
            "      - run: python3 tools/ghost.py\n"           # 実在しない
            "      - run: python3 $ds/varpath.py\n",          # 変数入り→スキップ
            encoding="utf-8")
        rc = main(["--workflows", str(wf), "--root", str(root)])
        if rc != 1:
            print(f"self-test NG: 実在しないパスで落ちなかった（exit {rc}）")
            ok = False
        (wf / "a.yml").write_text(
            "jobs:\n  a:\n    steps:\n      - run: python3 tools/real.py\n",
            encoding="utf-8")
        rc = main(["--workflows", str(wf), "--root", str(root)])
        if rc != 0:
            print(f"self-test NG: 全部実在するのに落ちた（exit {rc}）")
            ok = False
    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
