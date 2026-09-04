#!/usr/bin/env python3
"""案内・参照しているファイルパスが実在するかを見る（2つのモード）。

  --workflows  CI（workflow の YAML）が参照するパス
  --sources    ソース・md の中で「python3 <path>」「bash <path>」の形で
               **人に案内しているパス**（--sources で有効化）
  --rules      rules.json の extends の鎖が指す先（--rules design/rules.json）


414 の実害（2026-08-28）: verify.yml が `harness/tools/staleness_check.py` を
参照する形で書かれていたのに、ローカルの判断で submodule を見送っており、
**CI が参照するパスが存在しない構成**になっていた。push して CI が落ちるまで
誰も気づけない状態は、関門を入れた意味を薄める。

使い方（リポジトリのルートで）:
    python3 tools/ci_path_check.py [--workflows .github/workflows]

見るもの・見ないもの:
  捕まえるもの: YAML の run / with に書かれた**変数を含まないパス**で、
                リポジトリ内に実在しないもの。--sources では、失敗メッセージや
                docstring が「これを実行してください」と案内するパスの不在
                （flash-compose 2026-08-28: 上流の sync_pending の案内文と
                案件の gate テスト5箇所が、同日に削除済みのパスを指していた。
                孤児検査は「道具が呼ばれているか」を見るが、逆方向は誰も見ていない）
  捕まえないもの: `$ds/check_flutter_gaps.py` のような**変数を含むパス**
                （シェル変数は解決できず誤検出になるためスキップする。
                 414 の実測: `for ds in */` の展開を解決できず誤検出した）、
                clone してから使うパス（/tmp 等リポジトリ外）
  確かめた方法: attack/engine_attack_test.py ではなく本ファイル末尾の
                self-test（--self-test で合成 YAML に対して落ちる/通るを確認）

flash-compose の実害（2026-09-03・#43）: `design/rules.json` の extends が
**3つともリポジトリの外**（~/dev/design-systems/… と ~/dev/design-harness/…）を
指していた。手元は隣接クローンがあるので 70 ファイル・11 ルールで通り、
**CI でだけ走査 0 ファイル**になった。CI は入れた日から一度も緑になっていない。
3つ目は submodule に同じファイルがあり、向け直したらレジストリ抜きでも
11 ルール・exit 0 で通った（実測）。

この道具は「CI に存在しないパスを参照している」構成を捕まえるために作ったのに、
**見ていたのは YAML と散文だけで、ルールの鎖を見ていなかった。** 同じ家族の
失敗が網の外にあった。--rules はそこを埋める。
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

#: パスらしい文字列。拡張子つきの相対パスだけを拾う（コマンド名や URL は拾わない）
PATH_RX = re.compile(
    r"(?<![\w/$])((?:[\w.-]+/)+[\w.-]+\.(?:py|sh|json|ya?ml|js|mjs|dart|md|txt))\b")


#: 人に案内している実行コマンド。`python3 design/foo.py` の <path> を拾う
INVOKE_RX = re.compile(
    r"\b(?:python3?|bash|sh|node|dart)\s+((?:[\w.-]+/)+[\w.-]+\.(?:py|sh|mjs|js|dart))")


#: この行は検査しない、という印（エンジンの harness-ignore と同じ考え方）
PATH_IGNORE_MARK = "path-check-ignore"


def invoked_paths_in(text):
    """「python3 <path>」の形で案内されているパスを拾う。"""
    out = []
    for line in text.splitlines():
        if "$" in line or "{{" in line:      # 変数入りはスキップ
            continue
        if PATH_IGNORE_MARK in line:         # 印のある行はスキップ
            continue
        for m in INVOKE_RX.finditer(line):
            p = m.group(1)
            if p.startswith(("tmp/", "var/", "usr/", "opt/", "home/", "<")):
                continue
            out.append(p)
    return out


def paths_in(yml_text):
    out = []
    for line in yml_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "$" in line:      # 変数を含む行はスキップ（解決できない）
            continue
        if "http://" in line or "https://" in line:
            line = re.sub(r"https?://\S+", "", line)
        for m in PATH_RX.finditer(line):
            p = m.group(1)
            if p.startswith(("tmp/", "var/", "usr/", "opt/", "home/")):
                continue
            out.append(p)
    return out


# ─── ルールの鎖（--rules）──────────────────────────────────────────────
#: 「この extends はリポジトリの外だが、CI で取得する」と宣言する場所。
#: 理由を書かせる（`figma_layout_test` の notChecked と同じ形）
OUTSIDE_DECL = "$extendsOutsideRepo"

MAX_CHAIN = 8


def _git_root(start):
    """start を含む git リポジトリのルート。取れなければ None。"""
    d = start if start.is_dir() else start.parent
    try:
        out = subprocess.run(["git", "-C", str(d), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return Path(out.stdout.strip()) if out.returncode == 0 else None


def _submodule_paths(root):
    """.gitmodules に並んだ submodule の相対パス。"""
    gm = root / ".gitmodules"
    if not gm.exists():
        return []
    return re.findall(r"^\s*path\s*=\s*(\S+)", gm.read_text(encoding="utf-8",
                                                             errors="ignore"),
                      re.M)


def _fetched_in_ci(workflows, target):
    """CI がこの参照先を取りに行っているように見えるか（断定はしない）。

    「CI にこのパスは無い」と言い切ると外れることがある。flash-compose の CI は
    レジストリを `../design-systems` に clone している（ただし REGISTRY_TOKEN が
    あるときだけ）。**取得の有無を機械で確かめるのは無理なので、宣言に寄せる。**
    ここは文言を和らげるためだけに使い、合否には効かせない。
    """
    if not workflows or not workflows.exists():
        return False
    names = {p.name for p in target.parents if p.name}
    blob = "\n".join(
        y.read_text(encoding="utf-8", errors="ignore")
        for y in sorted(workflows.glob("*.yml")) + sorted(workflows.glob("*.yaml")))
    return any(n in blob for n in names)


def _twin_in_repo(root, target):
    """リポジトリの中に、同じ名前で同じ中身のファイルがあれば返す。

    flash-compose で実際に起きた形。**外を指しているが、submodule に同じものが
    ある。** そこへ向け直せば CI でも解決する（実測で 11 ルール・exit 0）。
    """
    if not target.exists():
        return None
    try:
        want = target.read_bytes()
    except OSError:
        return None
    for cand in sorted(root.rglob(target.name)):
        if set(cand.relative_to(root).parts) & SOURCE_SKIP:
            continue
        try:
            if cand.read_bytes() == want:
                return cand.relative_to(root)
        except OSError:
            continue
    return None


def _chain(rules_path, root, seen=None):
    """extends の鎖を「(書いてある側, 書かれた文字列, 解決先, 宣言)」で並べる。

    design_check.load_rules と同じたどり方をするが、**解決できたかどうかに
    関わらず全部返す**（この道具は届かない先を見るのが仕事）。

    リポジトリの外へ出た先は**たどらない**。そこから先の相対参照は別の
    リポジトリの都合であって、この案件の CI が解決できるかとは関係がない
    （flash-compose の実測では、レジストリ自身がさらに外を指していたため、
    たどると同じ原因の指摘が3つに増えて読みにくかった）。
    """
    seen = seen or set()
    here = rules_path.resolve()
    if here in seen or len(seen) > MAX_CHAIN:
        return []
    seen = seen | {here}
    try:
        conf = json.loads(rules_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    out = []
    for rel in conf.get("extends", []):
        target = (rules_path.parent / rel).resolve()
        out.append((rules_path, rel, target, conf.get(OUTSIDE_DECL) or {}))
        if str(target).startswith(str(root) + "/"):
            out.extend(_chain(target, root, seen))
    return out


def check_rules(rules_path, root=None, workflows=None):
    """rules.json の extends が CI でも解決できる先を指しているかを見る。"""
    if not rules_path.exists():
        print(f"ルールがありません: {rules_path}（検査対象なし）", file=sys.stderr)
        return 2
    root = (root or _git_root(rules_path))
    if root is None:
        print(f"git リポジトリの外です: {rules_path}", file=sys.stderr)
        return 2
    root = root.resolve()

    links = _chain(rules_path, root)
    if not links:
        print(f"extends がありません: {rules_path}（このファイルだけで完結）")
        return 0

    if workflows is None:
        workflows = root / ".github" / "workflows"
    subs = _submodule_paths(root)
    errs, declared, inside = [], 0, 0
    used_subs = set()
    for owner, rel, target, decl in links:
        owner = owner.resolve()
        who = (owner.relative_to(root)
               if str(owner).startswith(str(root) + "/") else owner)
        try:
            r = target.relative_to(root)
        except ValueError:
            reason = decl.get(rel)
            if isinstance(reason, str) and reason.strip():
                declared += 1
                continue
            msg = [f"  {who} の extends `{rel}` はリポジトリの外を指しています",
                   f"    → {target}",
                   f"    CI にこのパスがある保証がありません。**届かない層の"
                   f"ルールは黙って落ちます。**"]
            if _fetched_in_ci(workflows, target):
                msg.append(f"    CI がこの名前を取得しているように見えます。"
                           f"取得しているなら理由つきで宣言してください"
                           f"（宣言があれば通ります）。")
            twin = _twin_in_repo(root, target)
            if twin:
                msg.append(f"    リポジトリの中に同じ中身があります: `{twin}`")
                msg.append(f"    そこを指すように書き換えてください"
                           f"（flash-compose はこれで CI が緑になりました）。")
            else:
                msg.append(f"    CI で取得するなら {rules_path.name} に理由つきで"
                           f"宣言してください:")
                msg.append(f'      "{OUTSIDE_DECL}": '
                           f'{{"{rel}": "CI ではレジストリを取得して解決する"}}')
            errs.append("\n".join(msg))
            continue
        inside += 1
        for s in subs:
            if str(r) == s or str(r).startswith(s + "/"):
                used_subs.add(s)
        if not target.exists():
            errs.append(f"  {who} の extends `{rel}` の先がありません\n"
                        f"    → {r}")

    # submodule を指しているなら、CI がそれを取得しているかまで見る。
    # `submodules:` を書き忘れた checkout は、外を指しているのと同じことになる
    if used_subs and workflows and workflows.exists():
        ymls = sorted(workflows.glob("*.yml")) + sorted(workflows.glob("*.yaml"))
        blob = "\n".join(y.read_text(encoding="utf-8", errors="ignore") for y in ymls)
        if ymls and "submodules:" not in blob:
            errs.append(f"  extends が submodule（{' / '.join(sorted(used_subs))}）"
                        f"を指していますが、\n"
                        f"    {workflows} のどの workflow も submodules を"
                        f"取得していません。\n"
                        f"    actions/checkout の with に `submodules: true` が"
                        f"要ります（無いと CI では空のままです）。")

    if errs:
        print("ルールの鎖が CI で解決できません（手元でだけ通ります）:",
              file=sys.stderr)
        print("\n".join(errs), file=sys.stderr)
        return 1
    note = f"（うち {declared} 件は理由つきで外を指す宣言あり）" if declared else ""
    print(f"extends の参照先 {len(links)} 件、すべて CI から解決できます{note}。")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="workflow の参照パスの実在検査")
    ap.add_argument("--workflows", type=Path, default=Path(".github/workflows"))
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--sources", nargs="*", default=None,
                    help="案内パスも検査する対象（既定: . 配下の *.py *.md *.sh）")
    ap.add_argument("--ignore", nargs="*", default=None,
                    help="除外する参照先の接頭辞。上流では design/ を除外する")
    ap.add_argument("--rules", type=Path,
                    help="rules.json の extends の鎖を見る（例: design/rules.json）")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    if args.rules is not None:
        # --workflows の既定（.github/workflows）は cwd 基準なので、そのまま渡すと
        # **別のリポジトリの CI を見てしまう。** 明示されたときだけ使う
        given = ("--workflows" in (argv if argv is not None else sys.argv[1:]))
        return check_rules(args.rules,
                           None if args.root == Path(".") else args.root,
                           args.workflows if given else None)

    if args.sources is not None:
        return check_sources(args.root, args.sources, args.ignore)

    if not args.workflows.exists():
        print(f"workflow がありません: {args.workflows}（検査対象なし）")
        return 0

    missing, checked = [], 0
    for yml in sorted(args.workflows.glob("*.yml")) + sorted(args.workflows.glob("*.yaml")):
        for p in paths_in(yml.read_text(encoding="utf-8")):
            checked += 1
            if not (args.root / p).exists():
                missing.append(f"  {yml.name}: {p}")
    if checked == 0:
        print("注意: 検査できたパスが0件です（全部が変数入り、またはパスが無い）")
        return 0
    if missing:
        print("CI が参照するパスが実在しません（push すると CI が落ちます）:",
              file=sys.stderr)
        print("\n".join(sorted(set(missing))), file=sys.stderr)
        return 1
    print(f"CI の参照パス {checked} 件、すべて実在します。")
    return 0


SOURCE_SKIP = {".git", "node_modules", "__pycache__", "build", "dist",
               ".dart_tool", "archive"}


def check_sources(root, globs, ignore=None):
    """ソース・md が案内しているパスが実在するかを見る。

    ignore: 除外する参照先の接頭辞。**上流のリポジトリ（design-harness）では、
    案内が「取り込む側のパス」を指すのが正しい**ため、`design/` を除外して使う。
    行単位の除外は path-check-ignore の印で行う。
    """
    patterns = globs or ["**/*.py", "**/*.md", "**/*.sh"]
    ignore = list(ignore or [])
    missing, checked, files = [], 0, 0
    for pat in patterns:
        for f in sorted(root.glob(pat)):
            if not f.is_file() or set(f.relative_to(root).parts) & SOURCE_SKIP:
                continue
            files += 1
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for p in invoked_paths_in(text):
                if any(p.startswith(i) for i in ignore):
                    continue
                checked += 1
                if not (root / p).exists():
                    missing.append(f"  {f.relative_to(root)}: {p}")
    if files == 0:
        print("注意: 走査したファイルが0件です（--sources の指定を確認）")
        return 0
    if missing:
        print("案内しているパスが実在しません（読んだ人が空振りします）:",
              file=sys.stderr)
        print("\n".join(sorted(set(missing))), file=sys.stderr)
        return 1
    print(f"案内パス {checked} 件（{files} ファイル）、すべて実在します。")
    return 0


def self_test():
    """この検査自身の妨害テスト（落ちるケースを1つ持つ）。"""
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        wf = root / ".github/workflows"
        wf.mkdir(parents=True)
        (root / "tools").mkdir()
        (root / "tools/real.py").write_text("", encoding="utf-8")
        (wf / "a.yml").write_text(
            "jobs:\n  a:\n    steps:\n"
            "      - run: python3 tools/real.py\n"
            "      - run: python3 tools/ghost.py\n"           # 実在しない
            "      - run: python3 $ds/varpath.py\n",          # 変数入り→スキップ
            encoding="utf-8")
        rc = main(["--workflows", str(wf), "--root", str(root)])
        if rc != 1:
            print(f"self-test NG: 実在しないパスで落ちなかった（exit {rc}）")
            ok = False
        (wf / "a.yml").write_text(
            "jobs:\n  a:\n    steps:\n      - run: python3 tools/real.py\n",
            encoding="utf-8")
        rc = main(["--workflows", str(wf), "--root", str(root)])
        if rc != 0:
            print(f"self-test NG: 全部実在するのに落ちた（exit {rc}）")
            ok = False
        # --sources: 案内パスの不在で落ちるか
        (root / "guide.md").write_text(
            "実行してください: python3 tools/real.py\n"
            "こちらも: python3 tools/gone.py\n", encoding="utf-8")   # self-test の合成
        rc = main(["--root", str(root), "--sources", "*.md"])
        if rc != 1:
            print(f"self-test NG: 案内パスの不在で落ちなかった（exit {rc}）")
            ok = False
        (root / "guide.md").write_text(
            "実行してください: python3 tools/real.py\n"
            "変数入りは無視: python3 $HARNESS/tools/x.py\n", encoding="utf-8")
        rc = main(["--root", str(root), "--sources", "*.md"])
        if rc != 0:
            print(f"self-test NG: 実在する案内だけなのに落ちた（exit {rc}）")
            ok = False

        # ─── --rules（#43・flash-compose 2026-09-03 の再現）────────────────
        # extends がリポジトリの外を指していると、手元だけ通って CI で走査 0 になる
        rr = root / "proj"
        (rr / "design").mkdir(parents=True)
        (rr / "sub" / "rules").mkdir(parents=True)
        outside = root / "registry"
        outside.mkdir()
        common = json.dumps({"file_extensions": [".dart"], "rules": [{"id": "a"}]})
        (outside / "flutter.json").write_text(common, encoding="utf-8")
        (rr / "sub" / "rules" / "flutter.json").write_text(common, encoding="utf-8")
        rp = rr / "design" / "rules.json"

        def with_rules(conf, wf_dir=None):
            rp.write_text(json.dumps(conf), encoding="utf-8")
            args = ["--rules", str(rp), "--root", str(rr)]
            if wf_dir:
                args += ["--workflows", str(wf_dir)]
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                return main(args), buf.getvalue()

        rc, out = with_rules({"extends": ["../../registry/flutter.json"]})
        if rc != 1:
            print(f"self-test NG: 外を指す extends で落ちなかった（exit {rc}）"); ok = False
        if "リポジトリの中に同じ中身があります" not in out or "sub/rules/flutter.json" not in out:
            print("self-test NG: 中にある同じファイルを教えていない"); ok = False

        rc, _ = with_rules({"extends": ["../../registry/flutter.json"],
                            "$extendsOutsideRepo": {
                                "../../registry/flutter.json": "CI で取得する"}})
        if rc != 0:
            print(f"self-test NG: 理由つきの宣言があるのに落ちた（exit {rc}）"); ok = False

        rc, _ = with_rules({"extends": ["../../registry/flutter.json"],
                            "$extendsOutsideRepo": {"../../registry/flutter.json": "  "}})
        if rc != 1:
            print(f"self-test NG: 理由が空の宣言を通した（exit {rc}）"); ok = False

        rc, _ = with_rules({"extends": ["../sub/rules/flutter.json"]})
        if rc != 0:
            print(f"self-test NG: リポジトリ内を指しているのに落ちた（exit {rc}）"); ok = False

        rc, _ = with_rules({"extends": ["../sub/rules/ghost.json"]})
        if rc != 1:
            print(f"self-test NG: 中にあるが存在しない先を通した（exit {rc}）"); ok = False

        rc, _ = with_rules({"rules": []})
        if rc != 0:
            print(f"self-test NG: extends が無いだけで落ちた（exit {rc}）"); ok = False

        # 鎖の途中（親の extends）が外を指していても捕まえる
        (rr / "sub" / "rules" / "chain.json").write_text(
            json.dumps({"extends": ["../../../registry/flutter.json"]}), encoding="utf-8")
        rc, _ = with_rules({"extends": ["../sub/rules/chain.json"]})
        if rc != 1:
            print(f"self-test NG: 鎖の2段目が外を指すのを見逃した（exit {rc}）"); ok = False

        # submodule を指すなら、CI がそれを取得しているかまで見る
        (rr / ".gitmodules").write_text('[submodule "sub"]\n\tpath = sub\n',
                                       encoding="utf-8")
        pwf = rr / ".github" / "workflows"
        pwf.mkdir(parents=True)
        (pwf / "v.yml").write_text("jobs:\n  a:\n    steps:\n"
                                   "      - uses: actions/checkout@v4\n",
                                   encoding="utf-8")
        rc, out = with_rules({"extends": ["../sub/rules/flutter.json"]}, pwf)
        if rc != 1:
            print(f"self-test NG: submodules 未取得の CI を通した（exit {rc}）"); ok = False
        if "submodules: true" not in out:
            print("self-test NG: submodules の直し方を教えていない"); ok = False
        (pwf / "v.yml").write_text("jobs:\n  a:\n    steps:\n"
                                   "      - uses: actions/checkout@v4\n"
                                   "        with:\n          submodules: true\n",
                                   encoding="utf-8")
        rc, _ = with_rules({"extends": ["../sub/rules/flutter.json"]}, pwf)
        if rc != 0:
            print(f"self-test NG: submodules を取得しているのに落ちた（exit {rc}）"); ok = False

    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
