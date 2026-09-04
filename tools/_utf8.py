"""出力の文字コードで**死なない**ようにする。import するだけで効く。

## なぜ要るか

ハーネスの道具は**日本語と絵文字を前提に出力を書く**が、それが端末に出せるかを
誰も見ていなかった。日本語 Windows のコンソール既定は cp932 で、絵文字を
`print` した時点で `UnicodeEncodeError` になる。

実害（flash-compose・2026-09-04）:

    File "tools/page_scope_check.py", line 95, in main
      print(f"フェーズ: {phase} / 参照してよいページ: {', '.join(allowed)}")
    UnicodeEncodeError: 'cp932' codec can't encode character '⚙'

**Python が例外で死ぬので、呼び出し側の `|| { echo "…に反する記録があります" }`
に落ちる。** 記録は正しいのに「記録が悪い」と表示され、Windows から見ると
「原因不明で push できない」になる。**嘘の理由で落ちるのが一番悪い。**

## 何をするか

標準出力・標準エラーを UTF-8 に張り替える。`errors="replace"` なので、
**UTF-8 を出せない端末でも死なずに文字化けで済む。**

`PYTHONUTF8=1` を環境で与える手もあり、`ci/verify.sh.template` は両方入れている
（互いの保険）。ただし**環境に頼ると、人が手で道具を呼んだときに外れる。**

## 効かない場面

- 出力を**ファイルへリダイレクト**したとき（そちらは元から UTF-8）
- `subprocess` で呼んだ**子プロセス**の出力（子も自分で import する）
"""
import sys


def _fix(stream):
    fn = getattr(stream, "reconfigure", None)
    if fn is None:
        return                      # 差し替えられている（試験など）。触らない
    try:
        fn(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        pass                        # **握りつぶす。** ここで落ちたら本末転倒


_fix(sys.stdout)
_fix(sys.stderr)
