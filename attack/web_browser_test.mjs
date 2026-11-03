import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { check } from '../engine/web_browser_check.mjs';

test('両ブラウザでスクロールと描画を確認し、破壊すると落ちる',async()=>{
  let broken=null;
  const server=createServer((req,res)=>{
    res.setHeader('content-type','text/html');
    res.end(`<html><body><div id="scroll" style="height:150px;overflow:${broken==='scroll'?'hidden':'auto'}"><div style="height:2000px">content</div></div><svg id="vector" width="32" height="32"><path d="M0 16H32" stroke="black" stroke-width="1" ${broken==='vector'?'visibility="hidden"':''}/></svg></body></html>`);
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  try{
    const config={chromiumChannel:process.env.HARNESS_TEST_CHROME_CHANNEL,pages:[{url:`http://127.0.0.1:${server.address().port}`,scroll:['#scroll'],vectors:['#vector']}]};
    const good=await check(config);
    assert.ok(!good.results.some(r=>r.status!=='checked'),JSON.stringify(good));
    assert.equal(good.results.length,4);
    for(const failure of ['scroll','vector']) {
      broken=failure;
      const bad=await check(config);
      assert.ok(bad.results.filter(r=>r.status==='failed').length===2,JSON.stringify(bad));
      if(failure==='vector')assert.equal(bad.results.filter(r=>r.kind==='scroll'&&r.status==='checked').length,2);
      assert.ok(bad.limits.some(s=>s.includes('実機')));
    }
  }finally{await new Promise(resolve=>server.close(resolve));}
});
