const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function ui() {
  const elements = new Map();
  const element = selector => {
    if (!elements.has(selector)) elements.set(selector, {
      innerHTML: '', textContent: '', value: '', disabled: false, hidden: false,
      insertAdjacentHTML(_where, value) { this.innerHTML += value; },
      scrollIntoView() {},
    });
    return elements.get(selector);
  };
  const sandbox = { URL, console, setTimeout: () => 0, clearTimeout() {},
    document: { querySelector: element }, CSS: { escape: x => x } };
  vm.createContext(sandbox);
  const source = fs.readFileSync(process.env.FRONTEND_SCRIPT || path.join(__dirname, '../../web/static/app.js'), 'utf8');
  // Run actual renderer/request code, omitting only DOM event binding and boot.
  const offset = source.indexOf('  /* ---------- 绑定 ---------- */');
  assert.ok(offset > 0);
  vm.runInContext(source.slice(0, offset) + `
    globalThis.testUi = {renderGateway,renderPromotion,miniMarkdown,sendFaqMessage,
      submitReview,resetSession,state,faqChats,fieldHtml,collectForm,renderReport,renderFusion,moneyYuan,fillDefaults};
  })();`, sandbox);
  return { ...sandbox.testUi, sandbox, element };
}

test('real search results render provider source_url links', () => {
  const app = ui();
  const html = app.renderGateway({skill_name:'web_search', route_reason:'search', result:JSON.stringify({
    mode:'live', results:[{title:'Official docs', source_url:'https://example.com/docs'}]})});
  assert.match(html, /href="https:\/\/example.com\/docs"/);
});

test('real image arrays render images and reject executable URLs', () => {
  const app = ui();
  const html = app.renderGateway({skill_name:'image_gen', result:JSON.stringify({images:[
    {image_url:'https://example.com/picture.png'}, {image_url:'javascript:alert(1)'}]})});
  assert.match(html, /<img src="https:\/\/example.com\/picture.png"/);
  assert.doesNotMatch(html, /(?:src|href)="javascript:/);
});

test('only program facts are labelled verified, not the model draft', () => {
  const app = ui();
  const html = app.renderPromotion({plan_markdown:'## 已核对的基础数据\n\n- 金额100分\n\n## 一、四方主张\n\nMODEL_DRAFT'});
  const end = html.indexOf('</div>');
  assert.match(html.slice(0, end), /金额100分/);
  assert.doesNotMatch(html.slice(0, end), /MODEL_DRAFT/);
  assert.match(html.slice(end), /MODEL_DRAFT/);
});

test('generated code escapes exactly once', () => {
  const html = ui().miniMarkdown('```python\nif a < b:\n```');
  assert.match(html, /a &lt; b/);
  assert.doesNotMatch(html, /&amp;lt;/);
});

test('FAQ reports the real failed result instead of an empty successful answer', async () => {
  const app = ui();
  app.state.sessionId = 'sess-000000000001';
  app.element('#faqInput').value = 'hello';
  app.sandbox.fetch = async () => ({ok:true, json:async () => ({status:'failed',steps:{s1:{
    status:'failed',error:{code:'TOOL_UNAVAILABLE',message:'service is unavailable'}}}})});
  await app.sendFaqMessage();
  assert.match(app.faqChats[app.state.sessionId][1].text, /service is unavailable/);
  assert.doesNotMatch(app.faqChats[app.state.sessionId][1].text, /未返回答案/);
});

test('session reset uses the new server session and clears old FAQ memory view', async () => {
  const app = ui();
  app.state.sessionId = 'old'; app.faqChats.old = [{text:'old secret'}];
  app.element('#navSelect').value = 'orchestrate';
  app.sandbox.fetch = async () => ({ok:true,json:async () => ({session_id:'new'})});
  await app.resetSession();
  assert.equal(app.state.sessionId, 'new');
  assert.equal(app.faqChats.old, undefined);
});

test('business forms use accessible Chinese labels and decimal yuan', () => {
  const html = ui().fieldHtml('refund_amount', {type:'number'}, 'refund_amount', true);
  assert.match(html, /退款金额（元）/);
  assert.match(html, /for="field-refund_amount"/);
  assert.match(html, /id="field-refund_amount"/);
  const text = ui().fieldHtml('goal', {type:'string'}, 'goal', true);
  assert.match(text, /textarea/);
});

test('form keeps decimal yuan unchanged and rejects excess precision', () => {
  const app = ui();
  const el = {tagName:'INPUT', type:'number', value:'1099.00',
    getAttribute(name) {return name === 'data-field' ? 'refund_amount' : 'number';}};
  const card = {querySelectorAll:()=>[el]};
  assert.equal(app.collectForm(card).refund_amount, 1099.00);
  el.value='1099.5'; assert.equal(app.collectForm(card).refund_amount,1099.5);
  el.value='1099.501'; assert.throws(()=>app.collectForm(card), /两位小数/);
  el.value='Infinity'; assert.throws(()=>app.collectForm(card), /合法数字/);
});

test('business results stay visible and technical detail is collapsed', () => {
  const html = ui().renderReport({status:'completed',task_id:'task-demo',steps:{s1:{
    step_id:'s1',capability_id:'m6.data_fusion',status:'completed',
    result:{data:{fused_data:{week:'2025-W41',conversion_rate:.14}}}}},
    events:[{sequence:1,step_id:'s1',status:'completed'}],final_results:{s1:{amount:1}}});
  assert.match(html,/14.00%/);
  assert.match(html,/<details class="diagnostics"><summary>查看原始结果 JSON/);
  assert.doesNotMatch(html,/<details[^>]*\bopen\b/);
});

test('in-flight FAQ prevents session reset and restores controls after completion', async () => {
  const app = ui(); app.state.sessionId='sess-demo'; app.element('#faqInput').value='hello';
  let release;
  app.sandbox.fetch = () => new Promise(resolve => {release=resolve;});
  const pending = app.sendFaqMessage();
  assert.equal(app.element('#btnReset').disabled, true);
  assert.equal(app.element('#btnNew').disabled, true);
  await app.resetSession();
  assert.equal(app.state.sessionId,'sess-demo');
  release({ok:true,json:async()=>({status:'failed',steps:{s1:{status:'failed',error:{message:'test outage'}}}})});
  await pending;
  assert.equal(app.element('#btnReset').disabled, false);
  assert.equal(app.element('#btnNew').disabled, false);
});

test('failed empty business output does not show misleading blank order facts', () => {
  const html = ui().renderReport({status:'failed',task_id:'task-demo',steps:{s1:{
    step_id:'s1',capability_id:'m2.order_tracking',status:'failed',
    error:{code:'NOT_FOUND',message:'订单不存在'},result:{data:{}}}}});
  assert.match(html,/订单不存在/);
  assert.doesNotMatch(html,/<dt>订单号<\/dt>/);
});


test('yuan display and defaults preserve cents and show two places', () => {
  const app=ui();
  assert.match(app.moneyYuan(500.01), /500.01 元/);
  assert.match(app.moneyYuan(1.2), /1.20 元/);
  assert.doesNotMatch(app.moneyYuan(500.01), /分/);
  const el={tagName:'INPUT',type:'number',value:'',getAttribute:()=> 'refund_amount'};
  app.fillDefaults({querySelectorAll:()=>[el]}, {refund_amount:500.01});
  assert.equal(el.value,'500.01');
});

test('full multiline errors preserve diagnostic IDs and escape markup', () => {
  const message='M4 意图路由：字段校验失败\n'+'x'.repeat(2000)+'<script>alert(1)</script>';
  const html=ui().renderReport({status:'failed',steps:{s1:{step_id:'s1',
    capability_id:'m4.capability_gateway',status:'failed',
    error:{code:'CONTRACT_MISMATCH',message,request_id:'req-debug',trace_id:'trace-debug',retryable:false}}}});
  assert.match(html, /完整错误详情/);
  assert.ok(html.includes('x'.repeat(2000)));
  assert.match(html,/trace-debug/);
  assert.doesNotMatch(html,/<script>/);
});
