# push 直後に各案件でやること（順番どおり）

design-harness を push したあと、各案件で1回ずつ実行します。
**この順番でないと成立しません**（道具が submodule の古いピンに無いため）。

## 1. submodule を最新にする

    git -C design/harness pull origin main        # FlashEnglish / aub / planttalk
    git -C site/design/harness/harness pull origin main   # qnd-database

`__pycache__` で pull が止まる場合は先に:

    git -C design/harness checkout -- "engine/__pycache__"

## 2. verify.sh に共通検査の段を足す

`design/harness/ci/verify.sh.template` の次の段を、案件の verify.sh に写します。

| 段 | 道具 | 設定 |
|---|---|---|
| 種まき | `seed_check.py` | `design/seeds/` |
| 見なかったもの | `gap_report.py` | `design/gaps.json` |
| 期待値の出どころ | `expectation_source_check.py` | `design/expectations.json` |
| 書き出しの器 | `exporter_check.py` | `design/exporters.json` |
| 条件9 の網羅 | `tree_test_check.py` | `design/tree-tests.json` |
| 指紋の一致 | `fingerprint_parity.py` | （設定なし） |
| 段の健全性 | `stage_check.py` | `--verify design/verify.sh` |

**設定ファイルは全部コミット済み**です。道具が届けば、そのまま通ります。

## 3. 通ることを確かめる

    ./design/verify.sh

いま入っている `allow` / `notVerifiable` は**期限つきの宣言**で、
**2026-11-30 を過ぎると落ちます**。期限までに直すか、理由を書き直してください。

| 案件 | 期待値の出どころ | 書き出しの器 | 条件9 |
|---|---|---|---|
| FlashEnglish | 14件 | 4件 | 0件 |
| aub-familywalk | 10件 | 24件 | 0件 |
| planttalk | 18件 | 2件 | 7件 |
| qnd-database | — | 2件 | — |

## 4. FlashEnglish の verify.sh は形式が違う

`step "..."` の形を使っていないため、`stage_check` が段を1つも拾えず落ちます。
雛形の `step` 形式に寄せるか、ハーネスの道具を `design/harness/tools/` 経由で
呼ぶようにしてください（どちらでも `stage_check` は拾えます）。
