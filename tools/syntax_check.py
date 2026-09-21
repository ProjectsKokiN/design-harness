#!/usr/bin/env python3
"""**そもそもその言語として読めるか**だけを見る（2026-09-21 新設）。

## これは型検査ではありません

読めるかどうかだけです。**import の解決も、型も、名前も見ません。**
`MBTIGroup` が無いような誤りは捕まりません（`swift_symbol_check.py` が拾います）。
**「0 件だから通る」とは言えません。**出力にもそう書きます。

## なぜ要るか

実害（2026-09-20・PlantTalk）: Mac mini のビルドが 3 回落ち、**3 回とも別の層**でした。

    1 回目  MBTIGroup が無い / ColorBrand という型が無い  → 名前の照合が拾う
    2 回目  Space.chipGap が無い                        → 同上
    3 回目  **閉じ括弧が 1 つ足りない**                   → どの段も見ていなかった

3 回目は `.sheet` の修飾子を機械的に削ったときに `var body` を閉じる `}` まで
消していたものです。**Xcode の無い機体でも 1 秒で分かる**のに、
ビルドの往復 1 回を使いました。

## なぜ型検査でないのか

**iOS の SDK がこの機体にありません。**`-parse` は SDK が要らないので通ります
（PlantTalk で実測: `swiftc -parse` が Command Line Tools だけの機体で動き、
Mac mini が報告したのと**同じエラーを同じ行番号で**出しました。所要 1 秒）。

**Xcode のある機体では `-typecheck` のほうが強い**ので、そちらを使ってください。

## 終了コード

    0 … 確かめて合格
    1 … 確かめて違反（読めない）
    2 … **確かめられなかった**（道具が無い・走査対象が 0 件・設定が無い）

**道具が無いときに 0 を返さない。**「回せなかった」と「綺麗」は違います。

## 設定（案件の design/syntax.json）

    {
      "sources": ["Sources"],
      "拡張子": ".swift",
      "コマンド": ["swiftc", "-parse"],
      "$なぜこのコマンドか": "…"
    }
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--self-test" in argv or "--selftest" in argv:
        return self_test()
    if "--config" not in argv:
        print("--config <案件>/design/syntax.json を渡してください", file=sys.stderr)
        return 2
    cfg_path = Path(argv[argv.index("--config") + 1])
    if not cfg_path.exists():
        print(f"設定がありません: {cfg_path}", file=sys.stderr)
        print("  **置いていないことと、対象 0 件は別です。**", file=sys.stderr)
        return 2
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    root = Path(argv[argv.index("--root") + 1]) if "--root" in argv else cfg_path.resolve().parent.parent
    cmd = cfg.get("コマンド") or []
    if not cmd:
        print("設定に『コマンド』がありません", file=sys.stderr)
        return 2
    if not shutil.which(cmd[0]):
        print(f"× 回せませんでした: {cmd[0]} がこの機体にありません（構文は未確認です）",
              file=sys.stderr)
        print("  **『回せなかった』と『綺麗』は違います。**", file=sys.stderr)
        return 2

    ext = cfg.get("拡張子") or ".swift"
    files = []
    for d in (cfg.get("sources") or []):
        p = root / d
        files += sorted(str(f) for f in p.rglob(f"*{ext}")) if p.is_dir() else (
            [str(p)] if p.is_file() else [])
    if not files:
        print(f"{ext} のファイルが 1 件もありません: {cfg.get('sources')}", file=sys.stderr)
        print("  **0 件は『綺麗』ではなく『見ていない』です。**", file=sys.stderr)
        return 2

    r = subprocess.run([*cmd, *files], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=str(root))
    print(f"構文: {len(files)} ファイルを {' '.join(cmd)} で読みました")
    print("  **これは型検査ではありません。**import の解決も型も名前も見ていません。"
          "**0 件でも通るとは限りません。**")
    if r.returncode != 0:
        errs = [l for l in (r.stderr or "").splitlines() if ": error:" in l]
        print("\n**Swift として読めない箇所があります:**", file=sys.stderr)
        for l in (errs or (r.stderr or "").splitlines())[:10]:
            print(f"  {l}", file=sys.stderr)
        print("\n  **ビルドはここで止まるので、この先の誤りは出てきません。**",
              file=sys.stderr)
        return 1
    return 0


def self_test() -> int:
    import tempfile
    ok = True
    have = shutil.which("swiftc")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); (root / "design").mkdir(); (root / "src").mkdir()
        cfgp = root / "design" / "syntax.json"
        cfg = {"sources": ["src"], "拡張子": ".swift", "コマンド": ["swiftc", "-parse"]}

        def write(code, c=None):
            (root / "src" / "A.swift").write_text(code, encoding="utf-8")
            cfgp.write_text(json.dumps(c or cfg, ensure_ascii=False), encoding="utf-8")

        def run():
            return main(["--config", str(cfgp), "--root", str(root)])

        if have:
            write("struct A { var x = 1 }\n")
            if run() != 0:
                print("self-test NG: 読める形で落ちました"); ok = False
            write("struct A { var x = 1 \n")          # 閉じ括弧が無い
            if run() != 1:
                print("self-test NG: **読めない形を通しました**"); ok = False
        else:
            print("注意: swiftc がこの機体に無いので、読める/読めないの 2 件は飛ばしました")

        # **道具が無ければ 2**（0 を返さない）
        write("struct A { }\n", {**cfg, "コマンド": ["swiftc_no_such_tool", "-parse"]})
        if run() != 2:
            print("self-test NG: **道具が無いのに 2 を返しませんでした**"); ok = False

        # **走査 0 件は 2**
        (root / "src" / "A.swift").unlink()
        cfgp.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        if run() != 2:
            print("self-test NG: **0 件を通しました**（見ていないのに緑）"); ok = False

        cfgp.unlink()
        if run() != 2:
            print("self-test NG: 設定が無いのに 2 を返しませんでした"); ok = False

    print("self-test: " + ("OK" if ok else "NG"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
