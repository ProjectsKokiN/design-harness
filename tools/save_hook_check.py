#!/usr/bin/env python3
"""**保存時フック（PostToolUse）が、実際に違反を捕まえられるか**を見る（#125・2026-09-19）。

## 実害（2026-09-19・planttalk-ios）

`.claude/settings.json` の PostToolUse が `CLAUDE_PROJECT_DIR` だけに頼っており、
**この変数が未設定だったため `/design/design_check.py` を探して毎回落ちていました。**
つまり**保存時の禁止パターン検査は一度も走っていませんでした。**

今回は落ちて気づけましたが、**見つからないときに `exit 0` する書き方**だと
同じことが起きても静かに走らないまま進みます。

`hook_check.py` は pre-push（`core.hooksPath`）だけを見ており、
**保存時フックには同じ見張りがありませんでした。**
2026-09-07 に pre-push で「フックはあるが効いていない」を直したのと同じ型の穴が、
もう一方に残っていたことになります。

## どう確かめるか

**宣言を読むだけでは足りません**（書いてあっても効いていないのが実害でした）。
**種を1つ仕込んで、フックのコマンドを実際に走らせ、0 以外で終わることを見ます。**

## 終了コード

  0 … フックが種を捕まえた（**効いています**）
  1 … フックが種を素通りした、または設定が無い
  2 … 確かめられなかった（設定が読めない・種を作る材料が無い）
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

SETTINGS = (".claude/settings.json", ".claude/settings.local.json")


def hook_commands(root: Path) -> list[tuple[str, str]]:
    """(設定ファイル, コマンド) の一覧。PostToolUse のものだけ。"""
    out = []
    for rel in SETTINGS:
        p = root / rel
        if not p.is_file():
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue  # mutation-ok: 壊れた設定は config_schema_check の担当
        for entry in (d.get("hooks", {}).get("PostToolUse") or []):
            for h in (entry.get("hooks") or []):
                cmd = h.get("command")
                if h.get("type") == "command" and cmd:
                    out.append((rel, cmd))
    return out


def _chain(path: Path, seen=None) -> list[Path]:
    """`extends` を辿る。**辿らないと参照先のルールが見えません。**

    FlashEnglish は自分のファイルに1件しか持たず、残りはレジストリ側にあります
    （2026-09-19 実測）。
    """
    seen = seen if seen is not None else set()
    path = path.resolve()
    if path in seen or not path.is_file():
        return []
    seen.add(path)
    out = [path]
    try:
        d = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return out
    for rel in d.get("extends") or []:
        if isinstance(rel, str):
            out += _chain(path.parent / rel, seen)
    return out


def seed_from_rules(root: Path) -> tuple[str, str, list[str]] | None:
    """**仕込みの中身と除外パスを rules.json から導く**（道具に書かない）。

    `_selftest.bad` を持つルールの1つ目を使います。**必ず当たる例**なので、
    フックが効いていれば捕まります。`extends` も辿ります。
    """
    for rel in ("design/rules.json", "rules.json"):
        top = root / rel
        if not top.is_file():
            continue
        exts, excl = [".dart"], []
        chain = _chain(top)
        for q in chain:
            try:
                d = json.loads(q.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue
            if d.get("file_extensions"):
                exts = d["file_extensions"]
            excl += [str(x) for x in (d.get("exclude_paths") or [])]
        for q in chain:
            try:
                d = json.loads(q.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue
            for r in d.get("rules") or []:
                if r.get("paths"):
                    continue      # 置き場が決まったルールは、仮のファイルでは当たらない
                # **`warn` のルールを選んではいけません。** 検査エンジンは warn で
                # 0 を返すので、**効いているフックを「素通りした」と誤って咎めます**
                # （2026-09-19、実際に FlashEnglish で偽の赤を出しました）。
                if str(r.get("severity", "error")).lower() != "error":
                    continue
                bad = ((r.get("_selftest") or {}).get("bad") or [])
                if bad:
                    return str(bad[0]), str(exts[0]), excl
    return None


def probe_dir(root: Path, excl: list[str]) -> Path | None:
    """**除外パスに当たらない置き場**を選ぶ。

    `design/` は除外に入っている案件が多く、そこに仕込むと**素通りして見えます**
    （2026-09-19、実際にこの道具が偽の赤を出しました）。
    """
    def excluded(rel: str) -> bool:
        r = rel.rstrip("/") + "/"
        return any(r.startswith(str(e).rstrip("/") + "/") or str(e).rstrip("/") + "/" == r
                   for e in excl if str(e).strip() and "{{" not in str(e))

    for cand in ("lib", "Sources", "src", "site/src", "app", "."):
        d = root / cand
        if not d.is_dir():
            continue
        rel = "" if cand == "." else cand
        probe_rel = (rel + "/" if rel else "") + ".hook_probe"
        if not excluded(probe_rel):
            return d / ".hook_probe"
    return None


def run(root: Path) -> int:
    cmds = hook_commands(root)
    if not cmds:
        print("保存時フック（PostToolUse）の設定がありません。"
              "**書いていなければ、保存時の検査は走っていません。**")
        return 1
    seed = seed_from_rules(root)
    if not seed:
        print("仕込みの材料がありません（rules.json のルールに `_selftest.bad` が要ります）。"
              "\n  **0件は「綺麗」ではなく「見ていない」です**")
        return 2
    body, ext, excl = seed
    d = probe_dir(root, excl)
    if d is None:
        print("仕込みを置ける場所がありません（どの候補も exclude_paths に当たります）")
        return 2

    ng = []
    for rel, cmd in cmds:
        # **除外パスに当たらない置き場に置きます。** design/ に置くと素通りして見えます
        d.mkdir(parents=True, exist_ok=True)
        probe = d / f"probe{ext}"
        try:
            probe.write_text(body + "\n", encoding="utf-8")
            payload = json.dumps({"tool_input": {"file_path": str(probe)}})
            env = dict(os.environ)
            env.setdefault("CLAUDE_PROJECT_DIR", str(root))
            r = subprocess.run(["bash", "-lc", cmd], input=payload, cwd=root,
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", env=env, timeout=120)
            if r.returncode == 0:
                ng.append(f"  **仕込みを素通りしました**: {rel}\n"
                          f"      コマンド: {cmd}\n"
                          f"      仕込み: {body[:60]!r}\n"
                          f"      **このフックは効いていません。**保存時の検査は走っていません")
            else:
                print(f"  効いています: {rel}（終了コード {r.returncode}）")
        finally:
            probe.unlink(missing_ok=True)
            try:
                d.rmdir()
            except OSError:
                pass

    if ng:
        for l in ng:
            print(l)
        print(f"NG: 保存時フック {len(cmds)} 件のうち {len(ng)} 件が仕込みを素通りしました")
        return 1
    print(f"OK: 保存時フック {len(cmds)} 件とも、仕込みを捕まえました")
    return 0


def self_test() -> int:
    bad = []

    def case(name, got, want):
        if got != want:
            bad.append(f"{name}: {want} のはずが {got}")

    import contextlib, io
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        root = Path(d)
        (root / ".claude").mkdir()
        (root / "design").mkdir()
        (root / "lib").mkdir()          # **除外されない置き場**を用意する
        (root / "design" / "rules.json").write_text(json.dumps({
            "file_extensions": [".dart"],
            "exclude_paths": ["design/"],
            "rules": [
                # **warn は選ばれてはいけない**（先に置いても飛ばすこと）
                {"id": "w", "severity": "warn", "pattern": "WARNWARN",
                 "_selftest": {"bad": ["let w = WARNWARN"]}},
                {"id": "t", "severity": "error", "pattern": "NGNGNG",
                 "_selftest": {"bad": ["let x = NGNGNG"]}}]}), encoding="utf-8")

        def settings(cmd):
            (root / ".claude" / "settings.json").write_text(json.dumps({
                "hooks": {"PostToolUse": [{"matcher": "Edit",
                          "hooks": [{"type": "command", "command": cmd}]}]}}),
                encoding="utf-8")

        def go():
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = run(root)
            return rc, buf.getvalue()

        # **warn を飛ばして error のルールを選んでいるか**
        _seed = seed_from_rules(root)
        if not _seed or "NGNGNG" not in _seed[0]:
            bad.append(f"warn のルールを仕込みに選んでいる: {_seed[0] if _seed else None!r}")

        # **捕まえるフック**（仕込みの文字列を見つけたら 1 で終わる）
        settings("grep -q NGNGNG lib/.hook_probe/probe.dart && exit 1 || exit 0")
        case("捕まえるフックは通る", go()[0], 0)

        # **素通りするフック**（何もせず 0 で終わる。これが実害の形）
        settings("exit 0")
        rc, out = go()
        case("素通りするフックを捕まえる", rc, 1)
        if "効いていません" not in out:
            bad.append("素通りだと分かる文言が出ていない")

        # **見つからないときに exit 0 する書き方**（実害そのもの）
        settings('python3 "$NOPE/design/design_check.py" 2>/dev/null || exit 0')
        case("見つからず exit 0 する形を捕まえる", go()[0], 1)

        # 設定が無ければ 1
        (root / ".claude" / "settings.json").unlink()
        case("設定が無ければ 1", go()[0], 1)

        # **除外されている場所には置かない**（2026-09-19 に偽の赤を出した形）
        settings("test -f design/.hook_probe/probe.dart && exit 0 || exit 1")
        case("除外パスには置かない", go()[0], 0)

        # 仕込みの材料が無ければ 2
        settings("exit 1")
        (root / "design" / "rules.json").write_text(json.dumps({"rules": []}), encoding="utf-8")
        case("仕込みの材料が無ければ 2", go()[0], 2)

    if bad:
        for b in bad:
            print(b)
        print(f"NG: 自己検査が {len(bad)} 件落ちました。**この道具が空振りしています。**")
        return 1
    print("OK: 自己検査 8 件とも期待どおりでした")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="保存時フックが実際に違反を捕まえるか")
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    return run(a.root.resolve())


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # mutation-ok: 例外の帰り道。中からは通せない
        print(f"例外で止まりました: {e}")
        sys.exit(2)
