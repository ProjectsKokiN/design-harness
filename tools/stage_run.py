#!/usr/bin/env python3
"""検査の段を、時間切れつきで回す（#174）。同じ段を続けて回して、たまに落ちるかも見る（#178）。

使い方:
    stage_run.py --name <段の名前> [--timeout 秒] -- <コマンド...>
    stage_run.py --name <段の名前> --repeat 20 [--timeout 秒] -- <コマンド...>

**時間切れは「確かめられなかった（2）」です。** 止まった段は何も確かめていないので、
違反（1）とは分けます。止めるときは、段が起こした子のプロセスもまとめて止めます
（窓を出さない Chrome が残ると、次の段や次の push まで巻き込むため）。

実害（2026-10-24・portfolio）: 画面を測る段が 20 分以上止まり、verify.sh に時間切れが
無かったので、push も公開も黙って止まった。呼ぶ側を perl の alarm で包んで逃げていた。

--repeat は「たまに落ちる」を見つける。**1回でも落ちたら違反（1）**として、何回目に
落ちたかを出す。たまに落ちる検査は、本当の失敗を「またか」で見過ごさせる（#178）。
"""
import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401

DEFAULT_TIMEOUT = 600   # 秒。段ごとに --timeout か HARNESS_STAGE_TIMEOUT で変える
KILL_GRACE = 5          # 止める合図のあと、強制終了までに待つ秒数


def _start(cmd):
    if os.name == 'nt':
        return subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    # 新しいセッションにして、段が起こした子のプロセスもまとめて止められるようにする
    return subprocess.Popen(cmd, start_new_session=True)


def _kill_tree(proc):
    if os.name == 'nt':
        taskkill = shutil.which('taskkill')
        if taskkill:
            subprocess.run([taskkill, '/T', '/F', '/PID', str(proc.pid)],
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
        else:
            proc.kill()   # 子は残りうるが、少なくとも段そのものは止める
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=KILL_GRACE)
            # 親が終わっても、同じ組の子が残っていることがある。組が空になるまで合図を送る
            os.killpg(proc.pid, 0)
        except (subprocess.TimeoutExpired, ProcessLookupError, PermissionError):
            pass


def run_once(name, cmd, timeout):
    """1回回して、(終了コード, 時間切れか) を返す。"""
    try:
        proc = _start(cmd)
    except OSError as e:
        print(f'段「{name}」を始められませんでした: {e}（確かめられなかった）', file=sys.stderr)
        return 2, False
    try:
        return proc.wait(timeout=timeout), False
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        print(f'時間切れ: 段「{name}」が {timeout:g} 秒で終わりませんでした。'
              f'止めました（確かめられなかった）', file=sys.stderr)
        return 2, True


def run_repeat(name, cmd, timeout, times):
    failed = []
    for i in range(1, times + 1):
        rc, timed_out = run_once(name, cmd, timeout)
        if rc != 0:
            failed.append((i, rc, timed_out))
    if not failed:
        print(f'段「{name}」を {times} 回続けて回し、{times} 回とも通りました。')
        return 0
    print(f'段「{name}」を {times} 回回し、{len(failed)} 回落ちました'
          f'（中身を変えていないので、**たまに落ちる検査**です）:', file=sys.stderr)
    for i, rc, timed_out in failed:
        print(f'  {i} 回目: 終了コード {rc}' + ('（時間切れ）' if timed_out else ''), file=sys.stderr)
    if any(t for _, _, t in failed):
        return 2
    return 1


def self_test():
    import tempfile
    ok = True

    def check(cond, msg):
        nonlocal ok
        if not cond:
            print(f'self-test NG: {msg}')
            ok = False

    py = sys.executable
    check(run_once('通る', [py, '-c', 'pass'], 30) == (0, False), '通る段の終了コードを変えた')
    check(run_once('違反', [py, '-c', 'raise SystemExit(1)'], 30) == (1, False),
          '違反（1）をそのまま返していない')
    check(run_once('ほかのコード', [py, '-c', 'raise SystemExit(3)'], 30) == (3, False),
          '0・1・2 以外の終了コードを書き換えた')
    check(run_once('無いコマンド', ['この名前のコマンドは無い'], 30) == (2, False),
          '始められない段を確かめられなかった（2）にしていない')

    start = time.monotonic()
    rc, timed_out = run_once('止まる段', [py, '-c', 'import time; time.sleep(60)'], 1)
    check(rc == 2 and timed_out, f'時間切れを確かめられなかった（2）にしていない: {rc}')
    check(time.monotonic() - start < 20, '時間切れのあと、止まった段を待ち続けた')
    check(main(['--name', '止まる段', '--timeout', '1', '--',
                py, '-c', 'import time; time.sleep(60)']) == 2, 'main が時間切れで 2 を返さない')

    with tempfile.TemporaryDirectory() as td:
        if os.name != 'nt':
            # **子のプロセスまで止める**（窓を出さない Chrome が残る実害）
            pidfile = Path(td) / 'child.pid'
            child = ('import subprocess, sys, time\n'
                     f'p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])\n'
                     f'open({str(pidfile)!r}, "w").write(str(p.pid))\n'
                     'time.sleep(60)\n')
            run_once('子を起こす段', [py, '-c', child], 2)
            time.sleep(0.5)
            alive = False
            try:
                os.kill(int(pidfile.read_text(encoding='utf-8')), 0)
                alive = True
            except (ProcessLookupError, ValueError, OSError):
                pass
            check(not alive, '時間切れのあと、段が起こした子のプロセスが残っている')

        # **たまに落ちる**: 3回に1回だけ落ちる段
        counter = Path(td) / 'count'
        flaky = ('from pathlib import Path\n'
                 f'p = Path({str(counter)!r})\n'
                 'n = int(p.read_text()) + 1 if p.exists() else 1\n'
                 'p.write_text(str(n))\n'
                 'raise SystemExit(1 if n % 3 == 0 else 0)\n')
        check(run_repeat('たまに落ちる段', [py, '-c', flaky], 30, 6) == 1,
              '6回中2回落ちる段を違反（1）にしていない')
        check(main(['--name', '毎回通る段', '--repeat', '5', '--', py, '-c', 'pass']) == 0,
              '毎回通る段を通していない')
        check(run_repeat('ときどき止まる段',
                         [py, '-c', 'import time; time.sleep(60)'], 1, 1) == 2,
              '続けて回す中の時間切れを確かめられなかった（2）にしていない')

    check(main(['--name', '空', '--']) == 2, 'コマンドが無いのに通した')
    check(main(['--name', '負', '--timeout', '0', '--', py, '-c', 'pass']) == 2,
          '時間切れが 0 秒以下なのに通した')
    check(main(['--name', '回数', '--repeat', '0', '--', py, '-c', 'pass']) == 2,
          '回数が 0 なのに通した（空振り）')

    print('self-test: ' + ('OK' if ok else 'NG'))
    return 0 if ok else 1


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--self-test" in argv:
        return self_test()
    cmd = []
    if '--' in argv:
        i = argv.index('--')
        argv, cmd = argv[:i], argv[i + 1:]
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--name', required=True, help='段の名前（時間切れの表示に使う）')
    ap.add_argument('--timeout', type=float,
                    default=float(os.environ.get('HARNESS_STAGE_TIMEOUT', DEFAULT_TIMEOUT)),
                    help=f'秒（既定 {DEFAULT_TIMEOUT}。HARNESS_STAGE_TIMEOUT でも変えられる）')
    ap.add_argument('--repeat', type=int, default=1, help='続けて回す回数（たまに落ちるかを見る）')
    args = ap.parse_args(argv)
    if not cmd:
        print('回すコマンドがありません（-- のあとに書いてください）。確かめていません。', file=sys.stderr)
        return 2
    if args.timeout <= 0:
        print(f'時間切れの秒数が {args.timeout:g} です。0 より大きくしてください。確かめていません。',
              file=sys.stderr)
        return 2
    if args.repeat < 1:
        print(f'回数が {args.repeat} です。1 以上にしてください。確かめていません。', file=sys.stderr)
        return 2
    if args.repeat > 1:
        return run_repeat(args.name, cmd, args.timeout, args.repeat)
    rc, _ = run_once(args.name, cmd, args.timeout)
    return rc


if __name__ == '__main__':
    sys.exit(main())
