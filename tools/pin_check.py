#!/usr/bin/env python3
"""submodule のピンが上流の main からどれだけ遅れているかを知らせる。

一本化の目的は「仕組みの更新を全プロジェクトへ届けること」だが、submodule は
ピンで固定されるため、各案件が `git submodule update --remote` を叩くまで
届かない。「5案件に複製されて乖離していた」が「5案件が古いピンに固定されて
乖離する」に形を変えるだけになる（qnd/design-systems 第2便の提案4）。

**落とさない。知らせるだけ**（ピンの固定には意味があるため）。
--strict で exit 1 にできる（CI で強制したい案件向け）。

使い方（案件のルートで）:
    python3 design/harness/tools/pin_check.py [--submodule design/harness] [--strict]

捕まえるもの: ピンが上流 main より古いこと（何コミット遅れかを表示）
捕まえないもの: 上流の変更の中身（何が変わったかは design-harness の log を見る）
確かめた方法: --self-test は持たない。ネットワークが要るため、
  ピンを1つ古いコミットに手で動かして「遅れ 1」が出ることを目視で確認する
"""

import argparse
import subprocess
import sys
from pathlib import Path


def run(cmd, cwd=None):
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)


def main():
    ap = argparse.ArgumentParser(description="submodule ピンの遅れを知らせる")
    ap.add_argument("--submodule", type=Path, default=Path("design/harness"))
    ap.add_argument("--strict", action="store_true",
                    help="遅れていたら exit 1（既定は知らせるだけ）")
    args = ap.parse_args()

    sub = args.submodule
    if not (sub / ".git").exists() and not (sub / "engine").exists():
        print(f"submodule がありません: {sub}（git submodule update --init）",
              file=sys.stderr)
        return 2

    fetch = run(["git", "fetch", "-q", "origin", "main"], cwd=sub)
    if fetch.returncode != 0:
        print(f"上流を取得できませんでした（オフライン?）。ピンの遅れは未確認です:\n"
              f"  {fetch.stderr.strip()[:200]}", file=sys.stderr)
        return 0    # ネットワーク断で作業を止めない。ただし「未確認」と言う

    behind = run(["git", "rev-list", "--count", "HEAD..origin/main"], cwd=sub)
    if behind.returncode != 0:
        print(f"比較に失敗: {behind.stderr.strip()[:200]}", file=sys.stderr)
        return 2
    n = int(behind.stdout.strip() or 0)
    if n == 0:
        print("design-harness のピンは最新です。")
        return 0
    log = run(["git", "log", "--oneline", "HEAD..origin/main"], cwd=sub).stdout
    print(f"design-harness のピンが上流 main から {n} コミット遅れています。\n"
          f"取り込む: git -C {sub} pull origin main && git add {sub}\n"
          f"上流の変更:")
    print("\n".join(f"  {l}" for l in log.strip().splitlines()[:10]))
    return 1 if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
