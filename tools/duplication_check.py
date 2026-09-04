#!/usr/bin/env python3
"""複数案件に同じ名前で中身の違うファイルがないかを見る（2026-09-02 新設）。

## なぜ要るか

**このハーネスの改良は、いつも「どれかの案件が既に解いていたもの」の回収でした。**

| 解いていた案件 | 回収した日 | 何を |
|---|---|---|
| 5案件の複製 | 2026-08-28 | 検査エンジン（最大515行乖離していた） |
| flash-compose | 2026-08-30 | 余白の見張り（`no-raw-edgeinsets`） |
| aub-familywalk | 2026-09-02 | 識別子の規則・べき等検査・単体 component の収集 |

**回収の候補を見つけるのは、毎回手作業でした。** この道具はそれを機械にします。

同じ名前で中身が違うファイルは、次のどれかです。

1. **回収すべき共通の道具**（`figma_freshness.py` が3案件で別物だった）
2. **案件ごとに違って当然のもの**（`gen_colors.py` はデザインシステムが違えば違う）
3. たまたま名前が同じ

1 と 2 を機械では区別できないので、**2 は宣言してもらいます**（`allow` に
`why` と `reviewBy`）。宣言できないものが 1 の候補です。

## この検査が捕まえないもの

- **名前が違う同じ実装**（`verify.py` と `check_gen.py` が同じ中身、など）。
  名前でしか照合しない
- 中身の similarity（1バイト違えば「違う」と言う）
- 確かめた方法: --self-test（同名で中身が違うと落ちること・宣言で通ること）

## 使い方

    python3 tools/duplication_check.py --config duplication.json

    {
      "roots": ["~/dev/aub-familywalk", "~/dev/flash-compose", "~/dev/planttalk"],
      "scope": ["design"],
      "suffixes": [".py", ".js", ".mjs", ".sh"],
      "exclude": ["harness/", "__pycache__/", "seeds/"],
      "allow": [
        {"name": "gen_colors.py", "why": "デザインシステムごとに色の構造が違う",
         "reviewBy": "2026-12-31"}
      ]
    }
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

DATE_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def scan(roots, scope, suffixes, exclude):
    """name → [(案件, 大きさ, 指紋)] を返す。"""
    seen = {}
    for root in roots:
        root = Path(root).expanduser()
        if not root.exists():
            continue
        for sub in scope:
            base = root / sub
            if not base.exists():
                continue
            for f in sorted(base.rglob("*")):
                if not f.is_file() or f.suffix not in suffixes:
                    continue
                rel = str(f.relative_to(root))
                if any(x in rel for x in exclude):
                    continue
                seen.setdefault(f.name, []).append(
                    (root.name, f.stat().st_size,
                     hashlib.sha256(f.read_bytes()).hexdigest()[:8], rel))
    return seen


def main(argv=None):
    ap = argparse.ArgumentParser(description="案件をまたぐ複製を見つける")
    ap.add_argument("--config", type=Path)
    ap.add_argument("--today", help="期限の判定に使う日（試験用）")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()
    if not args.config:
        ap.error("--config が要ります（--self-test を除く）")

    try:
        conf = json.loads(args.config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"設定が読めません: {args.config}: {e}", file=sys.stderr)
        return 2

    from datetime import datetime, timezone
    today = args.today or datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")

    roots = conf.get("roots") or []
    if len(roots) < 2:
        print("roots が2つ未満です。**案件をまたがないと複製は見つかりません。**",
              file=sys.stderr)
        return 2

    allow, problems = {}, []
    for i, e in enumerate(conf.get("allow", [])):
        where = f"allow[{i}]"
        why, review = e.get("why"), e.get("reviewBy")
        if not e.get("name"):
            problems.append(f"{where}: name が要ります")
            continue
        if not why or len(str(why)) < 8:
            problems.append(f"{where}: why が要ります（なぜ案件ごとに違ってよいのか。8文字以上）")
        if not review or not DATE_RX.match(str(review)):
            problems.append(f"{where}: reviewBy が要ります（YYYY-MM-DD）")
        elif str(review) < today:
            problems.append(f"{where}: reviewBy {review} を過ぎています（{e['name']}）。"
                            f"まだ案件ごとに違ってよいか、見直してください")
        allow[e["name"]] = e

    seen = scan(roots, conf.get("scope") or ["design"],
                tuple(conf.get("suffixes") or [".py", ".js", ".mjs", ".sh"]),
                conf.get("exclude") or ["harness/", "__pycache__/"])
    if not seen:
        print("走査したファイルが0件です。**複製が無いのではなく、見ていません。**\n"
              f"  roots と scope を確かめてください: {roots} / {conf.get('scope')}",
              file=sys.stderr)
        return 2

    candidates = []
    for name, hits in sorted(seen.items()):
        if len(hits) < 2:
            continue
        if len({h for _, _, h, _ in hits}) == 1:
            continue                      # 同名・同内容は複製だが乖離していない
        if name in allow:
            continue
        candidates.append((name, hits))

    n_files = sum(len(v) for v in seen.values())
    print(f"案件をまたぐ複製: {len(roots)}案件 / {n_files}ファイルを走査 / "
          f"同名{len([k for k,v in seen.items() if len(v)>1])}種 / "
          f"宣言{len(allow)}件")

    if candidates:
        print(f"\n**同名で中身が違うファイルが {len(candidates)} 種あります。**"
              f" 回収の候補です:")
        for name, hits in candidates:
            spread = max(s for _, s, _, _ in hits) / max(
                min(s for _, s, _, _ in hits), 1)
            mark = "  ← **大きさが{:.0f}倍違います**".format(spread) if spread >= 2 else ""
            print(f"  - {name}{mark}")
            for proj, size, _, rel in hits:
                print(f"      {proj:<18} {size:>7}B  {rel}")
        print("\n  共有すべきものは design-harness へ回収してください。"
              "案件ごとに違ってよいものは allow に why と reviewBy を書いてください"
              "（**宣言できないものが回収の候補です**）。")

    if problems:
        print(f"\n宣言に問題があります:", file=sys.stderr)
        for m in problems:
            print(f"  - {m}", file=sys.stderr)
        return 1
    if candidates:
        return 1
    print("  OK: 同名で中身の違うファイルはありません。")
    return 0


def self_test():
    import tempfile
    ok = True

    def check(cond, msg):
        nonlocal ok
        if not cond:
            print(f"self-test NG: {msg}"); ok = False

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        for p in ("projA", "projB"):
            (base / p / "design").mkdir(parents=True)
        (base / "projA" / "design" / "same.py").write_text("X", encoding="utf-8")
        (base / "projB" / "design" / "same.py").write_text("X", encoding="utf-8")

        def cfg(**extra):
            d = {"roots": [str(base / "projA"), str(base / "projB")],
                 "scope": ["design"]}
            d.update(extra)
            (base / "c.json").write_text(json.dumps(d), encoding="utf-8")
            return ["--config", str(base / "c.json"), "--today", "2026-09-02"]

        check(main(cfg()) == 0, "同名・同内容で落ちた")

        # 同名で中身が違う → 落ちる（この道具の本題）
        (base / "projB" / "design" / "same.py").write_text("Y" * 500, encoding="utf-8")
        check(main(cfg()) == 1, "同名で中身が違うのに通した")

        # 宣言すれば通る
        check(main(cfg(allow=[{"name": "same.py", "why": "案件ごとに違ってよい理由",
                               "reviewBy": "2099-12-31"}])) == 0,
              "正しい宣言で落ちた")
        # why が無い宣言は落ちる
        check(main(cfg(allow=[{"name": "same.py"}])) == 1, "why の無い宣言を通した")
        # 期限切れ
        check(main(cfg(allow=[{"name": "same.py", "why": "案件ごとに違ってよい理由",
                               "reviewBy": "2020-01-01"}])) == 1,
              "期限切れの宣言を通した")

        # 走査が空振り → 落ちる
        check(main(cfg(scope=["no_such_dir"])) == 2, "空振りなのに通した")
        # roots が1つ → 落ちる
        d = {"roots": [str(base / "projA")], "scope": ["design"]}
        (base / "c.json").write_text(json.dumps(d), encoding="utf-8")
        check(main(["--config", str(base / "c.json")]) == 2, "roots 1つで通した")

    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
