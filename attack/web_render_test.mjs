// web_render_check の試験（候補1・#176・#177）。正常なページは両ブラウザ・両方の高さで違反0、
// 壊し方ごとに、その種類の違反で落ちることを見る。
// 正常なページには line-clamp で切った本文を置く（切られて描画されない行を「隠れている」と数えない・#189）。
import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { check } from '../engine/web_render_check.mjs';

const IMG = 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="60"><rect width="100" height="60" fill="#888"/></svg>');

function html(broken) {
  const anim = broken === 'flash'
    ? '@keyframes fadein{0%{opacity:1}50%{opacity:0}100%{opacity:1}} #img{animation:fadein .6s linear both}'
    : '@keyframes fadein{from{opacity:0}to{opacity:1}} #img{animation:fadein .3s ease-out both}';
  const gaugeTop = broken === 'height' ? 'calc(100vh - 600px)' : '200px';
  return `<!doctype html><html><head><meta charset="utf-8"><style>
body{margin:0;font:16px/1.5 sans-serif}
h1{margin:0 0 24px;font-size:24px;line-height:32px}
#img{display:block;width:100px;height:60px;margin:0}
${anim}
#card{width:200px;padding:8px}
#cap{opacity:0;transition:opacity .2s} #card:hover #cap{opacity:1}
.hid{opacity:0}
.row{position:relative;height:300px}
#rowtext{margin:0}
#gauge{position:absolute;left:0;top:${gaugeTop};width:300px;height:10px;background:#333}
#below{margin-top:1200px}
</style></head><body>
<h1 id="title">見出し</h1>
<img id="img" src="${IMG}" alt="">
<div id="card"><p id="name">名前</p><p id="cap">ホバーで出る説明</p></div>
<div class="row"><p id="rowtext">行の文字</p><div id="gauge"></div></div>
<p id="price">価格は ${broken === 'unit' ? '1200<br>円' : '1200円'}</p>
${broken === 'clip' ? '<div style="width:80px;overflow:hidden"><p id="clipt" style="width:200px;margin:0">切られる文字です切られる</p></div>' : ''}
${broken === 'occlude' ? '<div style="position:relative"><p id="occ" style="margin:0">隠れる文字</p><div style="position:absolute;inset:0;background:#fff"></div></div>' : ''}
${broken === 'spill' ? '<p id="sp" style="width:50px;white-space:nowrap">はみ出す長い文字です</p>' : ''}
${broken === 'brokenImage' ? '<img id="bad" src="/missing.png" alt="" style="width:20px;height:20px">' : ''}
<div id="clampbox"><p id="clamp" style="margin:0;width:120px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden">行数を制限した長い本文です行数を制限した長い本文です行数を制限した長い本文です行数を制限した長い本文です</p><p id="after" style="margin:0;background:#eee">次の段落</p></div>
<p id="below" ${broken === 'hidden' ? 'style="opacity:0"' : ''}>下の段落</p>
<script>
${broken === 'stuck' ? "document.getElementById('card').addEventListener('mouseenter',()=>document.getElementById('name').classList.add('hid'));" : ''}
${broken === 'cancel' ? "setTimeout(()=>{document.getElementById('img').style.animation='none'},100);" : ''}
</script></body></html>`;
}

const page = url => ({
  url,
  viewports: [{width: 800, height: 900}, {width: 800, height: 600}],
  hover: ['#card'],
  allow: [{check: 'hidden', selector: '#cap', why: 'ホバーで出す説明。止まっている間は隠す'}],
  gaps: [{a: '#title', b: '#img', gap: 24}],
  noOverlap: [['#rowtext', '#gauge']],
});

test('正常なページは違反0、壊し方ごとにその種類で落ちる', {timeout: 600000}, async () => {
  let broken = null;
  const server = createServer((req, res) => {
    if (req.url.startsWith('/missing')) { res.statusCode = 404; res.end(); return; }
    res.setHeader('content-type', 'text/html; charset=utf-8');
    res.end(html(broken));
  });
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const url = `http://127.0.0.1:${server.address().port}/`;
  const base = {chromiumChannel: process.env.HARNESS_TEST_CHROME_CHANNEL, settleMs: 4000};
  try {
    const good = await check({...base, pages: [page(url)]});
    const bad = good.results.filter(r => r.status !== 'checked');
    assert.equal(bad.length, 0, JSON.stringify(bad, null, 1));
    assert.equal(good.results.length, 4, '2ブラウザ × 2つの高さを測っていない');

    const expect = {
      clip: 'clipped', occlude: 'occluded', spill: 'spill', unit: 'unitWrap',
      brokenImage: 'brokenImage', hidden: 'hidden', flash: 'flash', stuck: 'hidden',
      cancel: 'cancel', height: 'overlap',
    };
    for (const [b, kind] of Object.entries(expect)) {
      broken = b;
      const r = await check({...base, pages: [page(url)]});
      for (const browser of ['chromium', 'webkit']) {
        const hits = r.results.filter(x => x.browser === browser && x.status === 'failed' && x.check === kind);
        assert.ok(hits.length > 0, `${b}: ${browser} で ${kind} を数えていない ${JSON.stringify(r.results.filter(x => x.browser === browser), null, 1)}`);
        if (b === 'height') {
          // 高さを変えたときだけずれる配置は、低いほうの高さでだけ落ちる（#177）
          assert.ok(hits.every(x => x.viewport === '800x600'), JSON.stringify(hits));
        }
        if (b === 'stuck') assert.ok(hits.some(x => x.phase.startsWith('ホバーの後')), JSON.stringify(hits));
      }
    }

    // 宣言が足りなければ確かめない（2 にする）
    await assert.rejects(check({pages: [{...page(url), viewports: [{width: 800, height: 900}]}]}), /viewports/);
    await assert.rejects(check({pages: [{...page(url), allow: [{check: 'hidden', selector: '#cap'}]}]}), /理由/);
  } finally { await new Promise(r => server.close(r)); }
});
