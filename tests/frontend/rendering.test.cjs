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
      submitReview,resetSession,state,faqChats};
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
