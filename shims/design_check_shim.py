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
sys.path.insert(0, str(HERE / "harness" / "engine"))

import design_check as engine  # noqa: E402

HOOKS = {
    # "soften": lambda path, project_root: False,
    # "notice": lambda path, project_root: None,
}

if __name__ == "__main__":
    sys.exit(engine.main(rules_path=HERE / "rules.json", hooks=HOOKS))
