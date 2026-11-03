#!/usr/bin/env python3
"""公開する前にGitの状態を確認する。コミット・公開は実行しない（#173）。"""
import argparse
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401


def inspect(root):
    try:
        r = subprocess.run(['git', '-C', str(root), 'status', '--porcelain=v1', '--untracked-files=all'],
                           capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
        if r.returncode:
            return 2, 'Gitの作業ツリーを確認できません'
        head = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], capture_output=True,
                              text=True, encoding='utf-8', errors='replace', timeout=30)
        if head.returncode:
            return 2, '公開元のコミットがありません'
        if r.stdout.strip():
            return 1, '未コミット・未追跡の変更があります。公開を止めます:\n' + r.stdout.strip()
        return 0, '公開元のコミット: ' + head.stdout.strip() + '（作業ツリーに変更なし）'
    except (OSError, subprocess.SubprocessError):
        return 2, 'Gitの状態を確認できません'


def self_test():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        def git(*args):
            subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True)
        assert inspect(root)[0] == 2
        assert main(['--root', str(root)]) == 2
        git('init', '-q')
        assert inspect(root)[0] == 2
        git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '--allow-empty', '-qm', 'fixture')
        assert inspect(root)[0] == 0
        (root / 'file.txt').write_text('x', encoding='utf-8')
        assert inspect(root)[0] == 1
        assert main(['--root', str(root)]) == 1
        git('add', 'file.txt')
        assert inspect(root)[0] == 1
    print('self-test: OK')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, default=Path('.'))
    ap.add_argument("--self-test", action='store_true')
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    rc, message = inspect(args.root)
    print(message)
    if rc == 1:
        return 1
    if rc == 2:
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
