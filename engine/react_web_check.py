"""固定した構文解析器を呼ぶ。未解析を検証済みへ丸めない。"""
import json
import shutil
import subprocess
import sys
from pathlib import Path
_TOOLS = str(Path(__file__).resolve().parent.parent / 'tools')
sys.path.insert(0, _TOOLS)
try:
    import _utf8  # noqa: F401  Windowsの出力規約を共有する
finally:
    sys.path.remove(_TOOLS)   # 読み込んだ側の検索パスを汚さない（#186）


def analyze(content, filename, mode=None):
    exe = shutil.which("node")
    failed = {"parsed": 0, "unparsed": 1, "violations": [], "limits": [], "files": 1}
    if not exe:
        return {**failed, "unknown": [{"line": 1, "why": "Nodeがありません"}]}
    try:
        result = subprocess.run(
            [exe, str(Path(__file__).with_suffix(".mjs"))],
            input=json.dumps({"source": content, "filename": filename, "mode": mode}),
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        if result.returncode:
            return {**failed, "unknown": [{"line": 1, "why": "React解析器を起動できません。ハーネスで npm ci --ignore-scripts を実行してください"}]}
        return json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as e:
        return {**failed, "unknown": [{"line": 1, "why": f"React解析に失敗しました: {type(e).__name__}"}]}


def summary(obs):
    reports = [o for o in obs if o.get("kind") == "react-analysis"]
    if not reports:
        return []
    out = [f"React解析: {len(reports)}ファイル / 解析できた {sum(r['parsed'] for r in reports)}件 / "
           f"解析できなかった {sum(r['unparsed'] for r in reports)}件 / "
           f"生値の違反 {sum(len(r['violations']) for r in reports)}件（解析件数は合格件数ではありません）"]
    for r in reports:
        out += [f"未解析: {r['file']}:{u['line']} — {u['why']}" for u in r['unknown']]
    out += sorted({"未検証範囲: " + s for r in reports for s in r["limits"]})
    return out
