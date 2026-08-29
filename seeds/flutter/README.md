# 種（seed）のひな形 — Flutter

**この中のコードは、わざと違反させてあります。** 案件の `design/seeds/` にコピーし、
`design/rules.json` の `exclude_paths` に `design/seeds/` を必ず入れてください
（通常の走査に混ぜると、意図した違反が本物の違反として報告されます）。

案件固有のルール（C層・D層）には、案件側で種を足してください。
`expected.json` の `"*": true` は「rules に載っている全ルールに種が要る」という宣言です。
段階導入の途中で種を書けないルールがあるうちは `"*"` を外し、書けたら真にしてください。

    python3 design/harness/tools/seed_check.py
