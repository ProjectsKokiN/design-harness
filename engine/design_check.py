#!/usr/bin/env python3
"""デザインハーネスの禁止パターン検査エンジン（全案件共通の正本）。

2026-08-28 に、5案件へ複製されていた design_check.py（テンプレとの差分が
最大515行まで乖離していた）を1本に統合したもの。各案件が実害から足した
機能をすべて取り込んである。案件側にはこのエンジンを呼ぶ薄いシムだけを置く
（shims/design_check_shim.py を参照）。

取り込んだ機能と出どころ:
  - extends の解決・--all・fail-closed・per-rule paths・発火ログ …… テンプレ
  - Bash 経由の編集の全走査（書き込みの気配で判定）……………………… テンプレ 2026-08-28
  - cp932 でも落ちない出力・壊れた正規表現の検出・読めないファイルの
    名指し・違反報告への相対パス・exclude_paths が paths を潰す検出 … flash-compose
  - ignore_for_file の解釈（lint との二重回答の解消）…………………… planttalk
  - exclude_files・理由つき harness-ignore・per-rule extensions・
    発火ログの source/kind・exit 4（対象外の区別）・
    Figma に画面が無いときは値ルールを警告に落とす（soften）………… qnd-database
  - require-near（不在検査）の実装 ……………………………………………… 新規。
    SKILL.md と rules-flutter.json が仕様として謳っていたのに実装が
    どこにも無く、aub の require-semantics-on-tappable が一度も
    走っていなかった（2026-08-28 の統合監査で発見）

終了コード:
  0 = 通過（hook では対象外・読めないも 0。Claude に余計なエラーを出さない）
  2 = 違反あり / 設定が壊れている（fail-closed）
  3 = 走査（scan）で読めないファイルがあった
  4 = 走査（scan）で対象外だった
  「呼んだ回数」と「中身を読んだ回数」を呼び出し側が区別するための区分
  （2026-08-25 QnD の Windows 追試: 97ファイル全部が素通りでも OK と出ていた）

環境変数:
  HARNESS_SOURCE = hook | scan | test（既定 hook）。test は発火ログに書かない。
  旧名 QND_HARNESS_SOURCE も後方互換で読む。
"""

import argparse
import fnmatch
import json
import re
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Windows の cp932 端末でも、UnicodeEncodeError で検査ごと落ちない・
# 日本語が「?」に潰れない、の両方を満たす（flash-compose 2026-08-24 ＋
# Windows 受け入れテスト 2026-08-28: errors=replace だけでは日本語出力が化け、
# PYTHONUTF8=1 を毎回付ける前提は配布できない）
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        try:
            _stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

IGNORE_MARK = "harness-ignore"

LOG_SOURCE = os.environ.get(
    "HARNESS_SOURCE", os.environ.get("QND_HARNESS_SOURCE", "hook"))

SKIP_CODE_TARGET = 4   # 走査時: 対象外
SKIP_CODE_UNREAD = 3   # 走査時: 読めなかった

#: 全走査で降りないディレクトリ（.rglob が node_modules に潜ると空振り検知が
#: 意味を成さないほど遅くなる）
SKIP_DIRS = {".git", "node_modules", "build", "dist", "dist-preview",
             ".dart_tool", ".idea", ".vscode", "archive", ".obsidian",
             "__pycache__", "Pods", ".gradle"}

#: Bash のコマンド文字列に書き込みの気配があるか。
#: 判定は控えめにし、読み取りと確信できるときだけ検査を省く
#: （見逃すくらいなら広めに検査する。全走査は実測 0.1〜0.3 秒級）
WRITE_HINTS = re.compile(
    r"(>>?|\btee\b|\bsed\b[^|;&]*-i|\bcp\b|\bmv\b|\btouch\b"
    r"|\bpatch\b|\bgit\s+apply\b|\bdd\b|<<|write_text|\.write\()")


# --------------------------------------------------------------------------
# 設定の読み込み
# --------------------------------------------------------------------------

def find_project_root(rules_path, config):
    """検査対象の起点。config の project_root（rules.json からの相対）が最優先。

    無ければ .git を上に探し、それも無ければ rules.json の親の親
    （<プロジェクト>/design/rules.json の慣例）。案件によって rules.json の
    深さが違うため（QnD は site/design/harness/）、固定段数にしない。
    """
    rel = (config or {}).get("project_root")
    if rel:
        return (rules_path.parent / rel).resolve()
    for parent in rules_path.resolve().parents:
        if (parent / ".git").exists():
            return parent
    return rules_path.resolve().parent.parent


def load_rules(rules_path, _seen=None):
    """rules.json を読み、extends を解決して1つの設定に合成する。

    合成の規則: extends（親）を先に読み、rules は 親→子 の順に連結する。
    file_extensions / exclude_paths / exclude_files は子に定義があれば子を使う。

    **extends は再帰的にたどる**（2026-08-29 に修正。それまで1段しか読まず、
    親の extends が黙って無視されていた——A層（スタック共通）→ B層（tokens から
    生成）→ C層（DS の命名）→ 案件、という鎖を組んだ時点で発覚し、A層の
    no-raw-color / no-raw-fontsize が消えた）。循環と深すぎる鎖は打ち切る。
    """
    if not rules_path.exists():
        return None
    try:
        child = json.loads(rules_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if _seen is None:
        _seen = set()
    here = rules_path.resolve()
    if here in _seen:
        print(f"デザインハーネス注意: extends が循環しています: {here}\n"
              f"  この輪をたどるのをやめます。", file=sys.stderr)
        return {"file_extensions": [], "exclude_paths": [],
                "exclude_files": [], "rules": []}
    _seen = _seen | {here}
    if len(_seen) > MAX_EXTENDS_DEPTH:
        print(f"デザインハーネス異常: extends の鎖が {MAX_EXTENDS_DEPTH} 段を"
              f"超えました: {here}", file=sys.stderr)
        return {"file_extensions": [], "exclude_paths": [],
                "exclude_files": [], "rules": []}

    merged = {"file_extensions": [], "exclude_paths": [],
              "exclude_files": [], "rules": []}
    for rel in child.get("extends", []):
        parent_path = (rules_path.parent / rel).resolve()
        if not parent_path.exists():
            print(
                f"デザインハーネス注意: extends の参照先が見つかりません: {parent_path}\n"
                f"  共通ルール抜きで検査を続けます。デザイン変更を検証するマシンでは\n"
                f"  design-systems リポジトリを ~/dev に隣接クローンしてください",
                file=sys.stderr,
            )
            continue
        parent = load_rules(parent_path, _seen)   # 再帰: 親の extends もたどる
        if parent is None:
            print(f"デザインハーネス注意: extends の読み込みに失敗: {parent_path}",
                  file=sys.stderr)
            continue
        for key in ("file_extensions", "exclude_paths", "exclude_files"):
            if not merged[key]:
                merged[key] = parent.get(key, [])
        merged["rules"].extend(parent.get("rules", []))

    for key in ("file_extensions", "exclude_paths", "exclude_files"):
        if child.get(key):
            merged[key] = child[key]
    merged["rules"].extend(child.get("rules", []))

    # 同じ id は後勝ち（子が親を上書き）。**上書きは黙って起こさない**
    # （2026-08-29。案件が A/B/C 層を並べて継承する形にしたため、同じ id が
    # 複数回載りうる。重複したまま走ると同じ違反が二重に報告される）
    seen_ids, deduped = {}, []
    for rule in merged["rules"]:
        rid = rule.get("id")
        if rid is None:
            deduped.append(rule)
            continue
        if rid in seen_ids:
            prev = deduped[seen_ids[rid]]
            if prev != rule:
                print(f"デザインハーネス注意: ルール '{rid}' が複数の層で定義され、"
                      f"後の定義で上書きしました（{rules_path}）。\n"
                      f"  同じ内容なら片方を消してください。違う内容なら、"
                      f"どちらが正かを決めてください。", file=sys.stderr)
            deduped[seen_ids[rid]] = rule
        else:
            seen_ids[rid] = len(deduped)
            deduped.append(rule)
    merged["rules"] = deduped

    # 案件側の追加設定はそのまま通す
    for key in ("ignore_reason_min", "project_root", "expected_targets",
                "expected_rules", "ignore_requires_expiry"):
        if key in child:
            merged[key] = child[key]
    return merged


#: extends の鎖の上限（A層→B層→C層→案件で4段。余裕をみて8）
MAX_EXTENDS_DEPTH = 8

KNOWN_RULE_TYPES = {"require-near"}


def unrunnable_rules(config):
    """実行できない形のルールを返す（aub 2026-08-28・最優先の指摘）。

    「12 → 13 とルール件数だけ増え、検査は1つも増えていない」を止める。
    require-semantics-on-tappable が実装の無いまま rules.json に載って
    一度も走らなかった病（幽霊ルール）と同じもので、統合で1件は動き出したが、
    type の綴りを1字間違えるだけで再発する状態だった。
    """
    out = []
    for rule in config.get("rules", []):
        rid = rule.get("id", "unknown")
        rtype = rule.get("type")
        if rtype is not None and rtype not in KNOWN_RULE_TYPES:
            out.append(f"  {rid}: type '{rtype}' をエンジンは知りません"
                       f"（知っているのは {sorted(KNOWN_RULE_TYPES)}）")
        elif rtype == "require-near":
            if not rule.get("trigger") or not rule.get("require"):
                out.append(f"  {rid}: require-near に trigger / require がありません")
        elif not rule.get("pattern"):
            out.append(f"  {rid}: pattern がありません（このルールは一度も走りません）")
    return out


def broken_patterns(config):
    """壊れた正規表現を持つルールを返す。壊れたルールは一度も走らないため、
    黙って続けると「検査しているつもりで何も見ていない」になる（flash-compose）。"""
    out = []
    for rule in config.get("rules", []):
        for key in ("pattern", "trigger", "require"):
            pat = rule.get(key)
            if not pat:
                continue
            try:
                re.compile(pat, re.DOTALL if rule.get("multiline") else 0)
            except re.error as e:
                out.append(f"  {rule.get('id', 'unknown')} の {key}: {e}")
    return out


def crushed_scopes(config):
    """exclude_paths がルールの paths を潰していないかを調べる。

    戻り値: (全部潰されたルールの一覧, 一部潰されたルールの注意文)。
    全部潰し＝そのルールは一度も走らないので error に格上げする
    （flash-compose 要望7・2026-08-28。「注意のまま通る」は
    緑なのに何も検査していないの一種）。
    """
    dead, notes = [], []
    excludes = [e.strip("/") for e in config.get("exclude_paths", [])]
    for rule in config.get("rules", []):
        scopes = rule.get("paths")
        if not scopes:
            continue
        alive = [s for s in scopes
                 if not any(("/" + e + "/") in ("/" + s.strip("/") + "/")
                            for e in excludes)]
        crushed = [s for s in scopes if s not in alive]
        if not alive:
            dead.append(f"  {rule.get('id', 'unknown')}: paths {scopes} が"
                        f" exclude_paths に全部潰されて一度も走りません")
        elif crushed:
            notes.append(f"  {rule.get('id', 'unknown')}: paths のうち {crushed} は"
                         f" exclude_paths に潰されています（走るのは {alive}）")
    return dead, notes


# --------------------------------------------------------------------------
# harness-ignore（行単位の除外）と ignore_for_file（ファイル単位の除外）
# --------------------------------------------------------------------------

def ignore_reason(line):
    """harness-ignore の行から、コメントとして書かれた理由だけを取り出す。

    コード自体を理由と数えないよう、コメントの中身に限る（qnd-database）。
    """
    text = None
    m = re.search(r"/\*(.*?)\*/", line, re.DOTALL)
    if m and IGNORE_MARK in m.group(0):
        text = m.group(1)
    if text is None:
        m = re.search(r"<!--(.*?)-->", line, re.DOTALL)
        if m and IGNORE_MARK in m.group(0):
            text = m.group(1)
    if text is None:
        m = re.search(r"//(.*)$", line)
        if m and IGNORE_MARK in m.group(0):
            text = m.group(1)
    if text is None:
        m = re.search(r"#(.*)$", line)
        if m and IGNORE_MARK in m.group(0):
            text = m.group(1)
    if text is None and "*/" in line and "/*" not in line:
        text = line.split("*/")[0]
    if text is None and "/*" in line and "*/" not in line:
        text = line.split("/*", 1)[1]
    if text is None:
        rest = line.replace(IGNORE_MARK, " ")
        if any(ch in rest for ch in "{};:"):
            return ""
        text = rest
    return text.replace(IGNORE_MARK, " ").strip(" \t*#-")


EXPIRES_RX = re.compile(r"(?:expires|期限)\s*[=:]\s*(\d{4}-\d{2}-\d{2})")


def is_ignored(lines, lineno, reason_min, require_expiry=False):
    """該当行または直前の行に harness-ignore があるか（lineno は1始まり）。

    戻り値は (除外するか, 拒否の種類)。拒否の種類:
      None = 拒否なし / "no_reason" = 理由不足 / "expired" = 期限切れ /
      "no_expiry" = 期限なし（require_expiry の案件のみ）

    期限（2026-08-29・aub の実害から）: `album.goal.height = 96` が
    harness-ignore で検査から外され、「あとで測る」のまま放置された。
    測れば分かる数（44 + 51.6）だった。**「あとで」が永久に有効な状態をやめる。**
    理由に `expires=YYYY-MM-DD` を書くと、その日を過ぎた除外は無効になる。
    config の `ignore_requires_expiry: true` で期限を必須にできる。
    """
    for n in (lineno, lineno - 1):
        if 1 <= n <= len(lines) and IGNORE_MARK in lines[n - 1]:
            line = lines[n - 1]
            reason = ignore_reason(line)
            if reason_min > 0 and len(reason) < reason_min:
                return False, "no_reason"
            m = EXPIRES_RX.search(line)
            if m:
                from datetime import date
                if date.fromisoformat(m.group(1)) < date.today():
                    return False, "expired"
            elif require_expiry:
                return False, "no_expiry"
            return True, None
    return False, None


def ignored_rule_ids(content):
    """ファイル全体で無効化されている規約の id を集める（planttalk 発）。

    lint（// ignore_for_file: avoid_raw_color）と rules.json の id
    （no-raw-color）は綴りが違うため、両方の形を受け取る。
    行単位の // ignore: は扱わない——このスクリプトの行対応は近似なので、
    「その行だけ除外したつもり」が効かない嘘を作らないため（planttalk の判断）。
    """
    ids = set()
    for line in content.splitlines():
        stripped = line.strip()
        if not (stripped.startswith("//") or stripped.startswith("/*")
                or stripped.startswith("#") or stripped.startswith("<!--")):
            continue
        if "ignore_for_file:" not in stripped:
            continue
        names = stripped.split("ignore_for_file:", 1)[1]
        names = names.split("*/")[0].split("-->")[0]
        for name in names.replace(" ", "").split(","):
            if not name:
                continue
            ids.add(name)
            ids.add(name.replace("_", "-"))
            ids.add("no-" + name.replace("avoid_", "").replace("_", "-"))
    return ids


# --------------------------------------------------------------------------
# スキャン
# --------------------------------------------------------------------------

def scan(content, config, path, project_root, soften=False):
    """全ルールを適用し (errors, warns, observations) を返す。

    soften=True のとき、soften_without_figma を持つルール（値のルール）は
    error でも warn に落とす。Figma に画面が無いものを作るとき、段に無い値が
    実在するため（QnD の MAP 線幅 1.5 等）。**書き方のルールは落ちない。**
    2026-08-28 ユーザー確定で全案件共通の仕様（違反は伝えるが、止めない）。
    """
    lines = content.splitlines()
    errors, warns, observations = [], [], []
    reason_min = int(config.get("ignore_reason_min", 0))
    require_expiry = bool(config.get("ignore_requires_expiry", False))
    file_ignored = ignored_rule_ids(content)
    default_exts = config.get("file_extensions", [])
    try:
        where = path.resolve().relative_to(project_root)
    except ValueError:
        where = path

    def note(rule, lineno, kind):
        observations.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "rule": rule.get("id", "unknown"),
            "severity": rule.get("severity", "error"),
            "file": str(where),
            "line": lineno,
            "kind": kind,                      # hit | ignored | ignored_no_reason
            "ignored": kind == "ignored",      # 旧スキーマ互換
            "source": LOG_SOURCE,
        })

    def report(rule, lineno, snippet, softened):
        entry = (
            f"- [{rule.get('id', 'unknown')}] {where} 行{lineno}\n"
            f"    禁止: {rule.get('forbidden', '')}\n"
            f"    代替: {rule.get('instead', '')}\n"
            f"    該当: {snippet.strip()[:120]}"
        )
        if rule.get("severity", "error") == "error" and not softened:
            errors.append(entry)
        else:
            warns.append(entry)

    def hit(rule, lineno, snippet):
        skip, rejected = is_ignored(lines, lineno, reason_min, require_expiry)
        if skip:
            note(rule, lineno, "ignored")
            return
        kind = {"no_reason": "ignored_no_reason",
                "expired": "ignored_expired",
                "no_expiry": "ignored_no_expiry"}.get(rejected, "hit")
        note(rule, lineno, kind)
        report(rule, lineno, snippet,
               softened=soften and rule.get("soften_without_figma"))

    for rule in config.get("rules", []):
        if rule.get("id") in file_ignored:
            note(rule, 0, "ignored")
            continue
        scopes = rule.get("paths")
        if scopes:
            rel = str(path).replace("\\", "/")
            if not any(scope in rel for scope in scopes):
                continue
        only = rule.get("extensions") or default_exts
        if only and path.suffix not in only:
            continue

        if rule.get("type") == "require-near":
            # 不在検査: trigger に当たった行の前後 within 行以内に require が
            # 無ければ違反。2026-08-28 まで実装がどこにも無く、この型のルールは
            # 一度も走っていなかった（aub の require-semantics-on-tappable）。
            trig = rule.get("trigger")
            req = rule.get("require")
            within = int(rule.get("within", 10))
            if not trig or not req:
                continue
            try:
                trig_rx, req_rx = re.compile(trig), re.compile(req)
            except re.error:
                continue
            for i, line in enumerate(lines, start=1):
                if not trig_rx.search(line):
                    continue
                lo = max(0, i - 1 - within)
                hi = min(len(lines), i + within)
                if any(req_rx.search(l) for l in lines[lo:hi]):
                    continue
                hit(rule, i, line)
            continue

        pattern = rule.get("pattern")
        if not pattern:
            continue  # unrunnable_rules() が読み込み時に落とすため、ここには来ない
        if rule.get("multiline"):
            try:
                rx = re.compile(pattern, re.DOTALL)
            except re.error:
                continue
            for m in rx.finditer(content):
                lineno = content.count("\n", 0, m.start()) + 1
                hit(rule, lineno, m.group(0).splitlines()[0])
        else:
            try:
                rx = re.compile(pattern)
            except re.error:
                continue
            for i, line in enumerate(lines, start=1):
                if rx.search(line):
                    hit(rule, i, line)
    return errors, warns, observations


# --------------------------------------------------------------------------
# 対象判定と走査
# --------------------------------------------------------------------------

def target_suffixes(config):
    exts = set(config.get("file_extensions", []))
    for rule in config.get("rules", []):
        exts.update(rule.get("extensions", []))
    return exts


def excluded_file(name, patterns):
    """除外ファイルの照合。完全一致 / 接尾辞 / glob の3通り。

    - `"design_check.py"` … 完全一致（従来どおり）
    - `".g.dart"`         … 接尾辞（`tokens.g.dart` に当たる）
    - `"harness-update-*.md"` … glob
    """
    for pat in patterns:
        if name == pat:
            return True
        if pat.startswith(".") and "*" not in pat and name.endswith(pat):
            return True
        if ("*" in pat or "?" in pat or "[" in pat) and fnmatch.fnmatch(name, pat):
            return True
    return False


def is_target(path, config, project_root):
    """対象拡張子・除外パス・除外ファイルの判定。

    `exclude_files` は**完全一致・接尾辞・glob** の3通りで当てる（2026-08-29 に修正）。
    それまで完全一致だけだったため、テンプレートが配っていた `".g.dart"` /
    `".freezed.dart"` が**1件も効いていなかった**。flash-compose と aub では
    `exclude_paths` の `lib/theme/` が生成物を覆っていて表に出ず、
    「生成物は除外できている」と誤解されたまま全案件に配られていた。

    除外は **project_root からの相対パス**に当てる（qnd 2026-08-28:
    絶対パスに当てていたため、"harness" が site/design/harness/ 配下の
    実ファイル19件まで食い、"archive" がクローン先のフォルダ名にまで
    当たって対象0件になった）。
    """
    if path.suffix not in target_suffixes(config):
        return False
    if excluded_file(path.name, config.get("exclude_files", [])):
        return False
    try:
        rel = path.resolve().relative_to(project_root).as_posix()
    except ValueError:
        rel = path.as_posix()
    posix = "/" + rel.strip("/") + "/"
    return not any(
        "/" + excluded.strip("/") + "/" in posix
        for excluded in config.get("exclude_paths", [])
    )


def scan_path(path, config, project_root, hooks):
    """1ファイルを走査する。戻りは (errors, warns, observations, 状態)。

    状態: True=読んだ / None=対象外 / str=読めなかった理由。
    読めないファイルを黙って握りつぶさない（flash-compose 2026-08-24。
    権限や文字コードで読めないファイルが検査されず痕跡も残らなかった）。
    """
    if not path.exists() or not path.is_file() or not is_target(path, config, project_root):
        return [], [], [], None
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return [], [], [], f"{path}: {e.__class__.__name__}"
    soften = bool(hooks.get("soften") and hooks["soften"](path, project_root))
    errors, warns, obs = scan(content, config, path, project_root, soften)
    return errors, warns, obs, True


def write_observations(log_path, observations):
    """発火ログ（仕組改善層）。マシンごとの記録なので git 管理しない。
    書けなくても検査は止めない。test 実行では書かない（QnD 2026-08-25:
    ログの77%が attack_test の一時ファイルで埋まり棚卸しが読めなかった）。"""
    if not observations or LOG_SOURCE == "test":
        return
    try:
        with log_path.open("a", encoding="utf-8") as f:
            for o in observations:
                f.write(json.dumps(o, ensure_ascii=False) + "\n")
    except OSError:
        pass


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------

def fail_config(rules_path):
    print(
        f"デザインハーネス異常: {rules_path} が読めません。"
        "検査が働いていないので、先に rules.json を直してください。",
        file=sys.stderr,
    )
    return 2


def ratchet(config, scanned=None):
    """宣言（expected_rules / expected_targets）を下回っていないかを見る。

    **design_check と gap_report の両方がここを呼ぶ。** 判定を2か所に書くと
    片方だけ直る（このリポジトリが何度も踏んだ形）。

    実害（2026-08-29・flash-compose）: 414 のルールを A/B/C 層に分けたところ、
    extends を1段しか読まない古い submodule のピンでは奥の層が届かず、ルールが
    12 → 7 に静かに減った。**それでも「違反なし」で exit 0 だった。**
    対象数のラチェット（expected_targets）はファイル数しか見ないので素通りする。

    実害（2026-09-03・flash-compose）: 同じ壊れた設定で design_check は落ちたのに、
    **gap_report は報告を出し続けた。** ルールが 5/11 しか読めないと exclude_paths も
    一緒に落ちるので、CI では走査 190 件・**発火 119 件（全部まちがい）**を出した。
    この道具の出力は完了レポートの冒頭にそのまま貼る決まりなので、
    **限界の報告書そのものが壊れた数字を出していた。**

    scanned に None を渡すと、ルール数だけを見る（走査の前に呼ぶため）。
    戻り値は (異常の文言, 注意の文言)。
    """
    errs, warns = [], []
    exp_rules = config.get("expected_rules")
    if isinstance(exp_rules, int):
        n = len(config.get("rules", []))
        if n < exp_rules:
            errs.append(f"デザインハーネス異常: 読み込めたルールが {n} 件で、"
                        f"宣言（expected_rules: {exp_rules}）を下回りました。\n"
                        f"  extends の参照先・submodule のピン・パスの綴りを"
                        f"確かめてください（届かない層は黙って落ちます）。\n"
                        f"  ルールが欠けると除外（exclude_paths）も一緒に落ちるので、"
                        f"この状態で出した件数は信用できません。\n"
                        f"  意図した減少なら rules.json の expected_rules を"
                        f"下げてください（差分が git に残ります）。")
        elif n > exp_rules:
            warns.append(f"デザインハーネス注意: ルールが {n} 件に増えています。"
                         f"rules.json の expected_rules（{exp_rules}）を"
                         f"上げてください。")

    expected = config.get("expected_targets")
    if isinstance(expected, int) and scanned is not None:
        if scanned < expected:
            errs.append(f"デザインハーネス異常: 中身を読んだファイルが {scanned} 件で、"
                        f"宣言（expected_targets: {expected}）を下回りました。\n"
                        f"  除外の書き方などで検査対象が黙って減っています"
                        f"（qnd 2026-08-28: 除外1語で19ファイル減っても緑だった）。\n"
                        f"  意図した減少なら rules.json の expected_targets を"
                        f"下げてください（差分が git に残ります）。")
        elif scanned > expected:
            warns.append(f"デザインハーネス注意: 対象が {scanned} 件に増えています。"
                         f"rules.json の expected_targets（{expected}）を"
                         f"上げてください。")
    return errs, warns


def run_all(config, rules_path, project_root, hooks, log_path):
    """全走査。読んだ数と対象外の数を必ず出す（空振り検知・QnD）。"""
    errors_total, warns_total = [], []
    scanned, skipped, unread = 0, 0, []
    for path in sorted(project_root.rglob("*")):
        if set(path.relative_to(project_root).parts) & SKIP_DIRS:
            continue
        errs, warns, obs, state = scan_path(path, config, project_root, hooks)
        if state is None:
            skipped += 1
            continue
        if isinstance(state, str):
            unread.append(state)
            continue
        scanned += 1
        errors_total.extend(errs)
        warns_total.extend(warns)
        write_observations(log_path, obs)

    errs, warns = ratchet(config, scanned)
    for w in warns:
        print(w, file=sys.stderr)
    if errs:
        print("\n".join(errs), file=sys.stderr)
        return 2

    if scanned == 0:
        print("デザインハーネス異常: 中身を読んだファイルが 0 です。"
              "走査が空振りしています（対象外 "
              f"{skipped} 件）。file_extensions と project_root を確認してください。",
              file=sys.stderr)
        return 2
    if unread:
        print("デザインハーネス異常: 読めないファイルがあります（検査されていません）:",
              file=sys.stderr)
        print("\n".join(f"  {u}" for u in unread), file=sys.stderr)
        return 2

    dead, notes = crushed_scopes(config)
    if notes:
        print("デザインハーネス注意:", file=sys.stderr)
        print("\n".join(notes), file=sys.stderr)
    if dead:
        print("デザインハーネス異常: 一度も走らないルールがあります:", file=sys.stderr)
        print("\n".join(dead), file=sys.stderr)
        return 2

    if errors_total:
        print("デザインハーネス違反を検出しました。代替案に従って修正してください。",
              file=sys.stderr)
        print("\n".join(errors_total), file=sys.stderr)
        if warns_total:
            print("\n注意（warn）:", file=sys.stderr)
            print("\n".join(warns_total), file=sys.stderr)
        print(f"\n（中身を読んだ {scanned} ファイル / 対象外 {skipped} ファイル）",
              file=sys.stderr)
        return 2
    if warns_total:
        print("デザインハーネス注意（warn）:", file=sys.stderr)
        print("\n".join(warns_total), file=sys.stderr)
    rule_n = len(config.get("rules", []))
    print(f"デザインハーネス: {scanned} ファイルを {rule_n} ルールで検査。違反なし。"
          f"（対象外 {skipped} ファイル / warn {len(warns_total)} 件）")
    return 0


def run_single(file_path, config, rules_path, project_root, hooks, log_path):
    """hook からの単一ファイル検査。"""
    path = Path(file_path)
    if hooks.get("notice"):
        hooks["notice"](path, project_root)

    scanning = LOG_SOURCE == "scan"
    if not is_target(path, config, project_root):
        return SKIP_CODE_TARGET if scanning else 0
    if not path.exists():
        # hook では消したファイルで来ることがあるので静かに通す。
        # 走査で読めないのは異常（QnD の Windows 追試: /c/... を C:\c\... と
        # 解釈して97ファイル全部が exists()=False で素通りしていた）
        if scanning:
            print(f"検査できませんでした（ファイルが見つかりません）: {file_path}",
                  file=sys.stderr)
            return SKIP_CODE_UNREAD
        return 0
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return SKIP_CODE_UNREAD if scanning else 0

    soften = bool(hooks.get("soften") and hooks["soften"](path, project_root))
    errors, warns, obs = scan(content, config, path, project_root, soften)
    write_observations(log_path, obs)

    if any(o.get("kind") == "ignored_expired" for o in obs):
        print(f"注意: 期限の切れた {IGNORE_MARK} を無効にしました（{path.name}）。\n"
              f"  直すか、理由と新しい期限（expires=YYYY-MM-DD）を書き直してください。",
              file=sys.stderr)
    if any(o.get("kind") == "ignored_no_expiry" for o in obs):
        print(f"注意: 期限の無い {IGNORE_MARK} は、この案件では無効です（{path.name}）。\n"
              f"  理由に expires=YYYY-MM-DD を添えてください。", file=sys.stderr)
    reason_min = int(config.get("ignore_reason_min", 0))
    if reason_min > 0 and any(o.get("kind") == "ignored_no_reason" for o in obs):
        print(f"注意: 理由の書かれていない {IGNORE_MARK} は無視しました（{path.name}）。\n"
              f"  「なぜその直値が要るのか」を同じ行か直前の行に"
              f" {reason_min} 文字以上で書いてください。", file=sys.stderr)

    if errors:
        print(f"デザインハーネス違反を検出しました（{path.name}）。"
              "代替案に従って修正してください。", file=sys.stderr)
        print("\n".join(errors), file=sys.stderr)
        if warns:
            print("\n注意（warn）:", file=sys.stderr)
            print("\n".join(warns), file=sys.stderr)
        return 2
    if warns:
        if soften:
            print(f"デザインハーネス注意（{path.name}・Figma に画面が無い対象）: "
                  f"{len(warns)} 件\n"
                  f"  値のルールは止めません。ただし直値のままだと Figma を直しても"
                  f"追従しません。Figma に足せる値なら足すのが本筋です。",
                  file=sys.stderr)
        else:
            print(f"デザインハーネス注意（warn・{path.name}）:", file=sys.stderr)
        print("\n".join(warns), file=sys.stderr)
    return 0


def main(argv=None, *, rules_path=None, hooks=None, log_path=None):
    """エンジンの入口。シムから rules_path と案件固有の hooks を渡して呼ぶ。

    hooks（すべて任意）:
      soften(path, project_root) -> bool
          そのファイルが「Figma に画面が無い対象」なら True（値ルールを warn に）
      notice(path, project_root) -> None
          層の注意など、検査の前に出す案件固有の表示
    """
    parser = argparse.ArgumentParser(
        description="デザインハーネスの禁止パターンを検査する")
    parser.add_argument("--all", action="store_true",
                        help="プロジェクト内の対象ファイルをすべて検査する")
    parser.add_argument("--rules", type=Path, default=None,
                        help="rules.json の場所（シムが指定する）")
    args = parser.parse_args(argv)

    rules_path = args.rules or rules_path
    if rules_path is None:
        rules_path = Path.cwd() / "design" / "rules.json"
    rules_path = Path(rules_path)
    hooks = hooks or {}

    config = load_rules(rules_path)
    if config is None:
        # fail-closed（テンプレ 2026-08-20 の是正。QnD 版は fail-open のままだった）
        return fail_config(rules_path)

    unrunnable = unrunnable_rules(config)
    if unrunnable:
        print("デザインハーネス異常: 実行できない形のルールがあります。"
              "件数に入るのに検査されないので、先に直してください。", file=sys.stderr)
        print("\n".join(unrunnable), file=sys.stderr)
        return 2

    broken = broken_patterns(config)
    if broken:
        print("デザインハーネス異常: 正規表現が壊れているルールがあります。"
              "そのルールは一度も走らないので、先に直してください。", file=sys.stderr)
        print("\n".join(broken), file=sys.stderr)
        return 2

    project_root = find_project_root(rules_path, config)
    log_path = log_path or (rules_path.parent / ".harness_log.jsonl")

    if args.all:
        global LOG_SOURCE
        if LOG_SOURCE == "hook":
            LOG_SOURCE = "scan"
        return run_all(config, rules_path, project_root, hooks, log_path)

    payload = None
    if not sys.stdin.isatty():
        try:
            payload = json.load(sys.stdin)
        except (json.JSONDecodeError, ValueError):
            payload = None
    tool_input = (payload or {}).get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    command = tool_input.get("command", "")

    if not file_path and command:
        # Bash 経由の編集: 対象ファイルを確実には特定できないので、
        # 書き込みの気配があれば全走査に倒す（2026-08-28）
        if not WRITE_HINTS.search(command):
            return 0
        return run_all(config, rules_path, project_root, hooks, log_path)
    if not file_path:
        # 入力が無い手動実行は全走査と同じ扱い（stdin 待ちで固まらせない）
        return run_all(config, rules_path, project_root, hooks, log_path)

    return run_single(file_path, config, rules_path, project_root, hooks, log_path)


if __name__ == "__main__":
    sys.exit(main())
