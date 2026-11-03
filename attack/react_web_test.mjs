import test from 'node:test';
import assert from 'node:assert/strict';
import { analyze, analyzeExpectations } from '../engine/react_web_check.mjs';

const cases = [
  ['生の色・余白・角丸', '<div style={{ color: "white", padding:16, borderRadius:8 }}/>', 3, 0],
  ['入れ子', '<><div>{ok ? <span style={{marginTop:8}}/> : <span style={{borderRadius:4}}/>}</div></>', 2, 0],
  ['コメント・説明文字列', '<div>{/* padding:16; color:#fff */}<span title="style={{padding:16}} #fff" style={{padding:"var(--gap-xs)"}}/></div>', 0, 0],
  ['静的スプレッド', 'const s={padding:16}; const A=()=> <div style={{...s, borderRadius:8}}/>;', 2, 0, true],
  ['未知スプレッドと既知の生値', '<div style={{...unknown, padding:16}}/>', 1, 1],
  ['JSXスプレッド', '<div {...props}><span style={{padding:16}}/></div>', 1, 1],
  ['静的テンプレート', '<div className={`p-[16px] rounded-[8px]`}/>', 2, 0],
  ['動的テンプレート', '<div className={`p-[16px] ${dynamic} rounded-[8px]`}/>', 2, 1],
  ['任意プロパティと状態', '<div className="hover:p-[16px] md:rounded-[8px] [padding:12px]"/>', 3, 0],
  ['CSS変数', '<div style={{color:"var(--text-neutral-default)",padding:"var(--gap-xs)",borderRadius:"var(--radius-s)"}}/>', 0, 0],
  ['単位を混ぜた式', '<div style={{padding:"calc(var(--gap-xs) + 8px)"}}/>', 1, 0],
  ['フォールバック', '<div style={{padding:"var(--gap-xs, 8px)"}}/>', 1, 0],
  ['並記', '<div style={{padding:"var(--gap-xs) 8px"}}/>', 1, 0],
  ['無次元係数', '<div style={{padding:"calc(var(--gap-xs) * 2)"}}/>', 0, 0],
  ['左の無次元係数', '<div style={{padding:"calc(2 * var(--gap-xs))"}}/>', 0, 0],
  ['不正なCSS式を通さない', '<div style={{padding:"calc(var(--gap-xs) +*)"}}/>', 0, 1],
  ['未対応のCSS関数を通さない', '<div style={{padding:"mystery(var(--gap-xs))"}}/>', 0, 1],
  ['動的な混在式', '<div style={{padding:Spacing.md + 8}}/>', 1, 1],
  ['外部スタイル', '<div style={styles.card}/>', 0, 1],
  ['styleの条件分岐に生値がある', '<div style={flag ? {padding:16} : {padding:"var(--gap-xs)"}}/>', 1, 1],
  ['テンプレート内の色と動的値', '<div style={{color:`#fff ${x}`}}/>', 1, 1],
  ['計算キー', '<div style={{[key]:16}}/>', 0, 1],
  ['未知の関数', '<div style={{padding:compute()}}/>', 0, 1],
  ['トークンの任意値', '<div className="p-[var(--gap-xs)] rounded-[var(--radius-s)]"/>', 0, 0],
  ['意味付きクラス', '<div className="p-xs rounded-s bg-frame-neutral-default"/>', 0, 0],
  ['壊れた構文', '<div style={{padding:16}', 0, 1],
  ['循環', 'const s=s; const A=()=> <div style={s}/>;', 0, 1, true],
  ['不正な引用', '<div title="https://example.test/ // padding:16" style={{padding:16}}/>', 1, 0],
];
for (const suffix of ['tsx', 'jsx']) for (const [name, source, hits, missing, complete] of cases) {
  test(`${suffix}: ${name}`, () => {
    const r=analyze(complete ? source : `const A=()=>(${source});`, `a.${suffix}`);
    assert.equal(r.violations.length,hits,JSON.stringify(r));
    assert.equal(r.unparsed>0,missing>0,JSON.stringify(r));
    assert.ok(r.parsed>=r.violations.length || r.unparsed>0);
  });
}
test('文字列・正規表現をJSXと誤認しない', () => {
  const r=analyze('const s="<div style={{padding:16}}/>"; const r=/<div style=/; // #fff\n');
  assert.equal(r.parsed,0); assert.equal(r.violations.length,0);
});
test('対応関係の未検証範囲を出す', () => {
  const r=analyze('const A=()=> <div className="p-xs" style={{padding:"var(--gap-xs)"}}/>;');
  assert.ok(r.limits.some(x=>x.includes('Tailwind')));
  assert.ok(r.limits.some(x=>x.includes('Figma')));
});
test('未知のstyle参照を既知に丸めない',()=> {
  const r=analyze('import styles from "./styles"; const A=()=> <div style={styles}/>;');
  assert.equal(r.parsed,0); assert.equal(r.unparsed,1);
});
test('constオブジェクトが変更される場合は未解析に残す',()=> {
  const r=analyze('const s={padding:"var(--gap-xs)"}; s.padding=16; const A=()=> <div style={s}/>;');
  assert.equal(r.unparsed,1);assert.equal(r.parsed,0);
});
test('更新演算子・alias経由の変更を検証済みにしない',()=> {
  for (const source of [
    'const s={padding:0}; s.padding++; const A=()=> <div style={s}/>;',
    'const s={padding:0}; const alias=s; alias.padding=16; const A=()=> <div style={s}/>;',
    'const s={padding:0}; const container={inner:s}; container.inner.padding=16; const A=()=> <div style={s}/>;',
  ]) {
    const r=analyze(source); assert.equal(r.unparsed,1);assert.equal(r.parsed,0);
  }
});
test('引数・catchの同名変数を外側の定数と取り違えない',()=> {
  for (const source of [
    'const s={padding:"var(--gap-xs)"}; function A(s){return <div style={s}/>;}',
    'const s={padding:"var(--gap-xs)"}; function A({s}){return <div style={s}/>;}',
    'const s={padding:"var(--gap-xs)"}; try {throw 0;} catch(s){const A=()=> <div style={s}/>;}',
  ]) {
    const r=analyze(source);assert.equal(r.unparsed,1);assert.equal(r.parsed,0);
  }
});
test('Webの期待値の直書きを検出する',()=>{
  const r=analyzeExpectations('const ok=style.backdropFilter === "blur(8px)"; assert.equal(style.color,"rgb(0,0,0)");');
  assert.equal(r.violations.length,2);
  const good=analyzeExpectations('const ok=style.backdropFilter === expectedBlur; // variables.jsonから読む\n');
  assert.equal(good.violations.length,0);assert.equal(good.unparsed,1);
  const raw=analyzeExpectations('const ok=style.backdropFilter === "blur(8px)"; assert.equal(style.color,"rgb(0,0,0)");');
  assert.equal(raw.violations.length,2);
  const embedded=analyzeExpectations('await evaluate(`(()=>{return getComputedStyle(el).backdropFilter === "blur(8px)";})()`);');
  assert.equal(embedded.violations.length,1);
});
