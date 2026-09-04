#!/usr/bin/env python3
"""案内・参照しているファイルパスが実在するかを見る（2つのモード）。

  --workflows  CI（workflow の YAML）が参照するパス
  --sources    ソース・md の中で「python3 <path>」「bash <path>」の形で
               **人に案内しているパス**（--sources で有効化）


414 の実害（2026-08-28）: verify.yml が `harness/tools/staleness_check.py` を
参照する形で書かれていたのに、ローカルの判断で submodule を見送っており、
**CI が参照するパスが存在しない構成**になっていた。push して CI が落ちるまで
誰も気づけない状態は、関門を入れた意味を薄める。

使い方（リポジトリのルートで）:
    python3 tools/ci_path_check.py [--workflows .github/workflows]

見るもの・見ないもの:
  捕まえるもの: YAML の run / with に書かれた**変数を含まないパス**で、
                リポジトリ内に実在しないもの。--sources では、失敗メッセージや
                docstring が「これを実行してください」と案内するパスの不在
                （flash-compose 2026-08-28: 上流の sync_pending の案内文と
                案件の gate テスト5箇所が、同日に削除済みのパスを指していた。
                孤児検査は「道具が呼ばれているか」を見るが、逆方向は誰も見ていない）
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

#: パスらしい文字列。拡張子つきの相対パスだけを拾う（コマンド名や URL は拾わない）
PATH_RX = re.compile(
    r"(?<![\w/$])((?:[\w.-]+/)+[\w.-]+\.(?:py|sh|json|ya?ml|js|mjs|dart|md|txt))\b")


#: 人に案内している実行コマンド。`python3 design/foo.py` の <path> を拾う
INVOKE_RX = re.compile(
    r"\b(?:python3?|bash|sh|node|dart)\s+((?:[\w.-]+/)+[\w.-]+\.(?:py|sh|mjs|js|dart))")


#: この行は検査しない、という印（エンジンの harness-ignore と同じ考え方）
PATH_IGNORE_MARK = "path-check-ignore"


def invoked_paths_in(text):
    """「python3 <path>」の形で案内されているパスを拾う。"""
    out = []
    for line in text.splitlines():
        if "$" in line or "{{" in line:      # 変数入りはスキップ
            continue
        if PATH_IGNORE_MARK in line:         # 印のある行はスキップ
            continue
        for m in INVOKE_RX.finditer(line):
            p = m.group(1)
            if p.startswith(("tmp/", "var/", "usr/", "opt/", "home/", "<")):
                continue
            out.append(p)
    return out


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
    ap.add_argument("--sources", nargs="*", default=None,
                    help="案内パスも検査する対象（既定: . 配下の *.py *.md *.sh）")
    ap.add_argument("--ignore", nargs="*", default=None,
                    help="除外する参照先の接頭辞。上流では design/ を除外する")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    if args.sources is not None:
        return check_sources(args.root, args.sources, args.ignore)

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


SOURCE_SKIP = {".git", "node_modules", "__pycache__", "build", "dist",
               ".dart_tool", "archive"}


def check_sources(root, globs, ignore=None):
    """ソース・md が案内しているパスが実在するかを見る。

    ignore: 除外する参照先の接頭辞。**上流のリポジトリ（design-harness）では、
    案内が「取り込む側のパス」を指すのが正しい**ため、`design/` を除外して使う。
    行単位の除外は path-check-ignore の印で行う。
    """
    patterns = globs or ["**/*.py", "**/*.md", "**/*.sh"]
    ignore = list(ignore or [])
    missing, checked, files = [], 0, 0
    for pat in patterns:
        for f in sorted(root.glob(pat)):
            if not f.is_file() or set(f.relative_to(root).parts) & SOURCE_SKIP:
                continue
            files += 1
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for p in invoked_paths_in(text):
                if any(p.startswith(i) for i in ignore):
                    continue
                checked += 1
                if not (root / p).exists():
                    missing.append(f"  {f.relative_to(root)}: {p}")
    if files == 0:
        print("注意: 走査したファイルが0件です（--sources の指定を確認）")
        return 0
    if missing:
        print("案内しているパスが実在しません（読んだ人が空振りします）:",
              file=sys.stderr)
        print("\n".join(sorted(set(missing))), file=sys.stderr)
        return 1
    print(f"案内パス {checked} 件（{files} ファイル）、すべて実在します。")
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
        # --sources: 案内パスの不在で落ちるか
        (root / "guide.md").write_text(
            "実行してください: python3 tools/real.py\n"
            "こちらも: python3 tools/gone.py\n", encoding="utf-8")   # self-test の合成
        rc = main(["--root", str(root), "--sources", "*.md"])
        if rc != 1:
            print(f"self-test NG: 案内パスの不在で落ちなかった（exit {rc}）")
            ok = False
        (root / "guide.md").write_text(
            "実行してください: python3 tools/real.py\n"
            "変数入りは無視: python3 $HARNESS/tools/x.py\n", encoding="utf-8")
        rc = main(["--root", str(root), "--sources", "*.md"])
        if rc != 0:
            print(f"self-test NG: 実在する案内だけなのに落ちた（exit {rc}）")
            ok = False

    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
