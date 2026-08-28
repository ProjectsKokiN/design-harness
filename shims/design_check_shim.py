#!/usr/bin/env python3
"""design_check.py のシム（案件側に置く薄い入口・テンプレート）。

検査エンジンの正本は design-harness リポジトリ（submodule）にあり、
案件側にはこのファイルだけを置く。hook のコマンドや verify.sh は
従来どおり design/design_check.py を呼べばよい（互換）。

配置: <プロジェクト>/design/design_check.py
前提: <プロジェクト>/design/harness/ に design-harness を submodule で取り込む
      git submodule add https://github.com/ProjectsKokiN/design-harness design/harness

案件固有の判定（Figma に画面が無い対象の soften、層の注意）が要る場合は
HOOKS に関数を足す。無ければ空のまま。
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE / "harness" / "engine"

if not (ENGINE / "design_check.py").exists():
    # submodule が取れていない＝検査が1行も走らない状態。黙って通さない。
    # このガードを import より前に置かないと、Python がシム自身を
    # design_check として import し、AttributeError という原因の読めない
    # 落ち方をする（flash-compose / aub / qnd の3案件が同日に指摘・2026-08-28）。
    # 保存時（hook）は作業を止めずに知らせるだけ、--all（verify.sh / CI）は落とす。
    # 関門は CI なので、ここで止めるのが正しい。
    print(
        f"デザインハーネス異常: 検査エンジンがありません（{ENGINE}）。\n"
        "  次を実行してください: git submodule update --init --recursive\n"
        "  取り込むまで、保存時の検査は働きません。",
        file=sys.stderr,
    )
    sys.exit(2 if "--all" in sys.argv else 0)

sys.path.insert(0, str(ENGINE))

import design_check as engine  # noqa: E402

# 読み込んだのが本当にエンジンかを確かめる（自己 import の最後の砦）
if not getattr(engine, "__file__", "").startswith(str(ENGINE)):
    sys.exit(f"デザインハーネス異常: エンジンではないものを読み込みました"
             f"（{getattr(engine, '__file__', '?')}）")

HOOKS = {
    # "soften": lambda path, project_root: False,
    # "notice": lambda path, project_root: None,
}

if __name__ == "__main__":
    sys.exit(engine.main(rules_path=HERE / "rules.json", hooks=HOOKS))
