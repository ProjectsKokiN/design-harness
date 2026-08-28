#!/usr/bin/env python3
"""エンジン自身の妨害テスト。**全機能について「落ちるケース」を1つずつ持つ。**

QnD の教訓（2026-08-28）: 「作ったのに動いていない検査」を6回踏み、症状は
すべて「緑なのに何も検査していない」だった。通ることの確認だけでは、
何も見ていない可能性を排除できない。エンジンを変えたら必ずこれを走らせる。

    python3 attack/engine_attack_test.py

依存なし（標準ライブラリのみ）。一時ディレクトリに合成プロジェクトを作り、
エンジンをサブプロセスで呼んで exit code と出力を確かめる。
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent / "engine" / "design_check.py"

PASSED, FAILED = [], []


def run(rules, files, stdin=None, args=None, expect_exit=None,
        expect_in=None, expect_not_in=None, label=""):
    """合成プロジェクトを作ってエンジンを1回呼ぶ。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".git").mkdir()                      # project_root 探索の目印
        design = root / "design"
        design.mkdir()
        (design / "rules.json").write_text(
            json.dumps(rules, ensure_ascii=False), encoding="utf-8")
        for rel, content in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")

        cmd = [sys.executable, str(ENGINE), "--rules", str(design / "rules.json")]
        cmd += args or []
        payload = json.dumps(stdin) if isinstance(stdin, dict) else stdin
        p = subprocess.run(cmd, input=payload, capture_output=True, text=True,
                           cwd=root,
                           env={**os.environ, "HARNESS_SOURCE": "test"})
        out = p.stdout + p.stderr

        problems = []
        if expect_exit is not None and p.returncode != expect_exit:
            problems.append(f"exit {p.returncode} (期待 {expect_exit})")
        for s in (expect_in or []):
            if s not in out:
                problems.append(f"出力に「{s}」が無い")
        for s in (expect_not_in or []):
            if s in out:
                problems.append(f"出力に「{s}」が出てはいけない")
        if problems:
            FAILED.append((label, problems, out[-400:]))
        else:
            PASSED.append(label)


RULES = {
    "version": 1,
    "file_extensions": [".dart"],
    "exclude_paths": ["lib/theme/"],
    "rules": [
        {"id": "no-raw-color", "severity": "error",
         "pattern": r"Color\(0x[0-9A-Fa-f]{8}\)",
         "forbidden": "生の色", "instead": "Sem.* を使う"},
        {"id": "warn-weight", "severity": "warn",
         "pattern": r"fontWeight:\s*FontWeight\.w\d+",
         "forbidden": "生のウェイト", "instead": "AppText を使う"},
    ],
}

BAD = "final c = Color(0xFFFF5800);\n"
GOOD = "final c = Sem.accent;\n"


def file_input(rel):
    return {"tool_input": {"file_path": rel}}


def main():
    # --- 基本: 捕まる・通る -------------------------------------------------
    run(RULES, {"lib/a.dart": BAD}, stdin=file_input("lib/a.dart"),
        expect_exit=2, expect_in=["no-raw-color"], label="基本: 違反で落ちる")
    run(RULES, {"lib/a.dart": GOOD}, stdin=file_input("lib/a.dart"),
        expect_exit=0, label="基本: 違反なしは通る")
    run(RULES, {"lib/theme/t.dart": BAD}, stdin=file_input("lib/theme/t.dart"),
        expect_exit=0, label="exclude_paths が効く")
    run({**RULES, "exclude_files": ["a.dart"]}, {"lib/a.dart": BAD},
        stdin=file_input("lib/a.dart"), expect_exit=0,
        label="exclude_files が効く（QnD 由来）")

    # --- fail-closed --------------------------------------------------------
    with tempfile.TemporaryDirectory() as td:
        p = subprocess.run(
            [sys.executable, str(ENGINE), "--rules", str(Path(td) / "nai.json"),
             "--all"],
            capture_output=True, text=True,
            env={**os.environ, "HARNESS_SOURCE": "test"})
        if p.returncode == 2 and "rules.json" in (p.stdout + p.stderr):
            PASSED.append("fail-closed: rules.json 不在で落ちる")
        else:
            FAILED.append(("fail-closed", [f"exit {p.returncode}"], p.stderr[-200:]))

    # --- 壊れた正規表現（一度も走らないルールの検出）-----------------------
    run({**RULES, "rules": RULES["rules"] + [
            {"id": "broken", "severity": "error", "pattern": "([unclosed"}]},
        {"lib/a.dart": GOOD}, stdin=file_input("lib/a.dart"),
        expect_exit=2, expect_in=["正規表現が壊れて"],
        label="壊れた正規表現で落ちる（flash 由来）")

    # --- harness-ignore -----------------------------------------------------
    run(RULES, {"lib/a.dart": "// 理由: スプラッシュだけの色 harness-ignore\n" + BAD},
        stdin=file_input("lib/a.dart"), expect_exit=0,
        label="harness-ignore（理由あり）で除外")
    run({**RULES, "ignore_reason_min": 10},
        {"lib/a.dart": "// harness-ignore\n" + BAD},
        stdin=file_input("lib/a.dart"), expect_exit=2,
        expect_in=["理由の書かれていない"],
        label="理由なし ignore は reason_min>0 で拒否（QnD 由来）")

    # --- ignore_for_file（planttalk 由来）----------------------------------
    run(RULES, {"lib/a.dart": "// ignore_for_file: no-raw-color\n" + BAD},
        stdin=file_input("lib/a.dart"), expect_exit=0,
        label="ignore_for_file（rules.json の id）")
    run(RULES, {"lib/a.dart": "// ignore_for_file: avoid_raw_color\n" + BAD},
        stdin=file_input("lib/a.dart"), expect_exit=0,
        label="ignore_for_file（lint の綴り avoid_raw_color）")

    # --- per-rule paths / extensions ---------------------------------------
    run({**RULES, "rules": [
            {"id": "ui-only", "severity": "error", "pattern": r"Prim\.",
             "paths": ["lib/ui/"]}]},
        {"lib/ui/s.dart": "x = Prim.a;\n"}, stdin=file_input("lib/ui/s.dart"),
        expect_exit=2, label="paths: 対象パスで捕まる")
    run({**RULES, "rules": [
            {"id": "ui-only", "severity": "error", "pattern": r"Prim\.",
             "paths": ["lib/ui/"]}]},
        {"lib/data/s.dart": "x = Prim.a;\n"}, stdin=file_input("lib/data/s.dart"),
        expect_exit=0, label="paths: 対象外パスは通る")
    run({**RULES, "rules": [
            {"id": "md-style", "severity": "error", "pattern": r"style=",
             "extensions": [".md"]}]},
        {"docs/a.md": '<div style="color:red">\n'}, stdin=file_input("docs/a.md"),
        expect_exit=2, label="extensions: ルール単位の拡張子（QnD 由来）")

    # --- multiline ----------------------------------------------------------
    run({**RULES, "rules": [
            {"id": "cross-line", "severity": "error", "multiline": True,
             "pattern": r"BoxDecoration\([^)]*?color:\s*Color\("}]},
        {"lib/a.dart": "BoxDecoration(\n  color: Color(0xFF000000),\n)\n"},
        stdin=file_input("lib/a.dart"),
        expect_exit=2, label="multiline: 行をまたぐ違反")

    # --- require-near（不在検査。2026-08-28 に初めて実装）-------------------
    REQ = {**RULES, "rules": [
        {"id": "require-semantics", "severity": "error", "type": "require-near",
         "trigger": r"GestureDetector\(", "require": r"Semantics\(",
         "within": 5, "forbidden": "識別子なしのタップ領域",
         "instead": "Semantics(identifier:) を近くに置く"}]}
    run(REQ, {"lib/a.dart": "GestureDetector(\n  onTap: f,\n)\n"},
        stdin=file_input("lib/a.dart"), expect_exit=2,
        label="require-near: 不在で落ちる")
    run(REQ, {"lib/a.dart": "Semantics(identifier: 'x',\n  child: GestureDetector(\n))\n"},
        stdin=file_input("lib/a.dart"), expect_exit=0,
        label="require-near: 近くにあれば通る")

    # --- soften（Figma に画面が無い対象は値ルールを warn に）----------------
    SOFT = {**RULES, "rules": [
        {"id": "no-raw-size", "severity": "error", "pattern": r"width:\s*\d",
         "soften_without_figma": True},
        {"id": "no-inline-style", "severity": "error", "pattern": r"style="}]}
    # soften は hooks 経由なので、エンジン単体では常に False（=error のまま）
    run(SOFT, {"lib/a.dart": "width: 240\n"}, stdin=file_input("lib/a.dart"),
        expect_exit=2, label="soften: hooks 無しでは error のまま")

    # --- Bash 経由 -----------------------------------------------------------
    run(RULES, {"lib/a.dart": BAD},
        stdin={"tool_input": {"command": "ls -la && grep -rn foo lib/"}},
        expect_exit=0, expect_not_in=["no-raw-color"],
        label="Bash: 読み取り系は検査しない")
    run(RULES, {"lib/a.dart": BAD},
        stdin={"tool_input": {"command": "sed -i s/a/b/ lib/a.dart"}},
        expect_exit=2, expect_in=["no-raw-color"],
        label="Bash: 書き込みの気配で全走査")

    # --- --all の空振り検知（QnD 由来）--------------------------------------
    run(RULES, {"lib/a.dart": GOOD}, args=["--all"], stdin="",
        expect_exit=0, expect_in=["ファイルを", "違反なし"],
        label="--all: 読んだ件数を必ず出す")
    run({**RULES, "file_extensions": [".nothing"]}, {"lib/a.dart": BAD},
        args=["--all"], stdin="",
        expect_exit=2, expect_in=["空振り"],
        label="--all: 1件も読まなければ失敗")

    # --- exclude_paths がルールの paths を全部潰す（flash 要望7の格上げ）----
    run({**RULES,
         "exclude_paths": ["lib/ui/"],
         "rules": [{"id": "ui-only", "severity": "error", "pattern": r"Prim\.",
                    "paths": ["lib/ui/"]}]},
        {"lib/a.dart": GOOD}, args=["--all"], stdin="",
        expect_exit=2, expect_in=["一度も走らない"],
        label="--all: paths が全部潰されたルールで落ちる")

    # --- 発火ログ -----------------------------------------------------------
    # HARNESS_SOURCE=test では書かない（QnD: ログの77%がテストで埋まった）
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".git").mkdir()
        d = root / "design"
        d.mkdir()
        (d / "rules.json").write_text(json.dumps(RULES), encoding="utf-8")
        (root / "lib").mkdir()
        (root / "lib/a.dart").write_text(BAD, encoding="utf-8")
        subprocess.run(
            [sys.executable, str(ENGINE), "--rules", str(d / "rules.json")],
            input=json.dumps(file_input("lib/a.dart")), capture_output=True,
            text=True, cwd=root, env={**os.environ, "HARNESS_SOURCE": "test"})
        if not (d / ".harness_log.jsonl").exists():
            PASSED.append("発火ログ: test では書かない")
        else:
            FAILED.append(("発火ログ", ["test なのに書いた"], ""))
        subprocess.run(
            [sys.executable, str(ENGINE), "--rules", str(d / "rules.json")],
            input=json.dumps(file_input("lib/a.dart")), capture_output=True,
            text=True, cwd=root, env={**os.environ, "HARNESS_SOURCE": "hook"})
        log = d / ".harness_log.jsonl"
        if log.exists() and '"kind": "hit"' in log.read_text(encoding="utf-8"):
            PASSED.append("発火ログ: hook では書く")
        else:
            FAILED.append(("発火ログ", ["hook で書かれていない"], ""))

    # --- 結果 ---------------------------------------------------------------
    print(f"妨害テスト: {len(PASSED)} 件 通過 / {len(FAILED)} 件 失敗")
    for label, problems, tail in FAILED:
        print(f"\nNG: {label}")
        for p in problems:
            print(f"  - {p}")
        if tail:
            print(f"  出力末尾: ...{tail}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
