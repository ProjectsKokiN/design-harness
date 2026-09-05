# 種（seed）のひな形 — Flutter

**この中のコードは、わざと違反させてあります。** 案件の `design/seeds/` にコピーし、
`design/rules.json` の `exclude_paths` に `design/seeds/` を必ず入れてください
（通常の走査に混ぜると、意図した違反が本物の違反として報告されます）。

案件固有のルール（C層・D層）には、案件側で種を足してください。
`expected.json` の `"*": true` は「rules に載っている全ルールに種が要る」という宣言です。
段階導入の途中で種を書けないルールがあるうちは `"*"` を外し、書けたら真にしてください。

    python3 design/harness/tools/seed_check.py

## 2つの経路から外す（両方やらないと落ちます）

種は**わざと違反させたコード**で、コンパイルされることを意図していません
（`Sem` など実在しない識別子を使います）。次の**2か所**から外してください。

1. **禁止パターン検査**: `design/rules.json` の `exclude_paths` に `design/seeds/`
2. **静的解析**: `analysis_options.yaml`（Flutter）に次を足す

```yaml
analyzer:
  exclude:
    - design/seeds/**
```

**2 を忘れると `flutter analyze` が種を解析して落ちます**（2026-08-30 に
FlashEnglish で実際に踏みました。`Undefined name 'Sem'` が5件）。
Web の案件なら tsconfig / eslint の除外に同じものを足してください。
