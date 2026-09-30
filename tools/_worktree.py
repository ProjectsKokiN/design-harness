"""いま手を入れているファイル（作業ツリー＋どのリモートにも無いコミット）を集める部品。

figma_freshness（変わった部品が作業と関係あるか・#138）と not_yet_check（作り直しと
無関係な push を通すか・#147）が**同じ読み方で**使います（2026-09-30 に共通にしました）。
"""
import subprocess
from pathlib import Path


def changed_files(root):
    """返り値は（ファイルの集まり, 全部見られたか）。

    **全部は見られなかったとき、「触っていない」とは言えません**（見ていないファイルに
    手が入っているかもしれない）。

    2026-09-28 に 2 つ直しました（FlashEnglish の実測）:
    - `git status --porcelain` の行を**先に strip してから 3 文字切っていた**ため、
      作業ツリーで変更しただけの行（先頭が空白）はパスの頭が欠けていた
    - 上流（`@{u}`）が無いと未 push のコミットを黙って見落としていた。
      **どのリモートにも無いコミット**（`HEAD --not --remotes`）で数える
    """
    out, complete = set(), True
    for args in (('status', '--porcelain'),
                 ('log', '--name-only', '--format=', 'HEAD', '--not', '--remotes')):
        r = subprocess.run(['git', '-c', 'core.quotepath=false', '-C', str(root), *args],
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
        if r.returncode != 0:
            complete = False
            continue
        for raw in r.stdout.splitlines():
            line = raw[3:] if args[0] == 'status' else raw
            line = line.strip().strip('"')
            if ' -> ' in line:
                line = line.split(' -> ', 1)[1].strip('"')
            if line:
                out.add(line)
    return out, complete


def repo_root(start):
    """`start` から上へたどって git の根を探す。見つからなければ None。"""
    cur = Path(start).resolve()
    for d in [cur, *cur.parents]:
        if (d / '.git').exists():
            return d
    return None
