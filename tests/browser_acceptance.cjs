/* 本機瀏覽器驗收：獨立資料庫與三個隔離的瀏覽器 context。 */
const { chromium } = require('playwright');
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('assert').strict;

const root = path.resolve(__dirname, '..');
const python = process.env.BUZZER_TEST_PYTHON || path.join(root, '.venv', 'Scripts', 'python.exe');
const browserPath = process.env.BUZZER_BROWSER || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'buzzer-browser-'));
const db = path.join(temp, 'acceptance.sqlite');
const port = 18763;
const base = `http://127.0.0.1:${port}`;
const serverCode = 'import sys; from app import create_app; app=create_app({"TESTING":True,"SECRET_KEY":"browser-test-only","DATABASE":sys.argv[1]}); app.run(host="127.0.0.1",port=int(sys.argv[2]),threaded=True,use_reloader=False)';
const server = spawn(python, ['-c', serverCode, db, String(port)], {cwd: root, stdio: ['ignore','pipe','pipe'], windowsHide: true});
let serverLog = '';
server.stdout.on('data', chunk => { serverLog += chunk.toString(); });
server.stderr.on('data', chunk => { serverLog += chunk.toString(); });
const evidence = path.join(root, 'docs', 'browser-evidence');
const step = name => console.log(`PASS ${name}`);
async function ready() {
  for (let i = 0; i < 100; i++) {
    if (server.exitCode !== null) throw Error('測試伺服器提前結束，請確認埠號未被占用');
    if (serverLog.includes(`Running on ${base}`)) return;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw Error('測試伺服器無法啟動');
}
async function run() {
  let browser;
  try {
    await ready();
    browser = await chromium.launch({headless:true, executablePath:browserPath});
    const contexts = await Promise.all([1,2,3].map(() => browser.newContext()));
    const [teacher, one, two] = await Promise.all(contexts.map(c => c.newPage()));
    await Promise.all([teacher,one,two].map(p => p.goto(base)));
    await teacher.getByRole('button', {name:'老師', exact:true}).click();
    await one.getByRole('button', {name:'第 1 組', exact:true}).click();
    await two.getByRole('button', {name:'第 2 組', exact:true}).click();
    await teacher.locator('#numbers').fill('1,2');
    await teacher.getByRole('button', {name:'設定測試題目'}).click();
    await teacher.getByRole('button', {name:'開始搶答'}).click();
    await Promise.all([one,two].map(p => p.getByText('活動階段：搶答中').waitFor()));
    step('三個獨立身分及活動同步');
    const q1 = p => p.locator('article').filter({hasText:'第 1 題'});
    const q2 = p => p.locator('article').filter({hasText:'第 2 題'});
    await q1(one).locator('input').fill('第一組答案');
    await q1(one).getByRole('button',{name:'提交答案'}).click();
    await q1(one).getByText('本組已提交').waitFor();
    await q1(two).locator('input').fill('第二組答案');
    await q1(two).getByRole('button',{name:'提交答案'}).click();
    await q1(two).getByText('本組已提交').waitFor();
    assert.equal(await one.getByText('第二組答案').count(), 0);
    assert.equal(await two.getByText('第一組答案').count(), 0);
    step('兩組提交及活動中資訊隔離');
    // Block only polling requests for one student, keeping POST /api/answer available.
    const block = route => route.abort();
    await one.route('**/api/state', block);
    await teacher.getByRole('button', {name:'結束搶答'}).click();
    await teacher.getByText('活動階段：已結束').waitFor();
    assert.equal(await one.locator('#phase').innerText(), '活動階段：搶答中');
    await q2(one).locator('input').fill('過期提交');
    const response = one.waitForResponse(r => r.url().endsWith('/api/answer') && r.request().method() === 'POST');
    await q2(one).getByRole('button', {name:'提交答案'}).click();
    assert.equal((await response).status(), 409);
    await one.getByText('目前不在搶答階段').waitFor();
    const query = spawnSync(python, ['-c', 'import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute("select count(*) from submissions where answer=?",("過期提交",)).fetchone()[0]); c.close()', db], {encoding:'utf8'});
    assert.equal(query.status, 0, query.stderr); assert.equal(query.stdout.trim(), '0');
    fs.mkdirSync(evidence, {recursive:true});
    await one.screenshot({path:path.join(evidence,'stale-rejected.png'), fullPage:true});
    step('舊頁面提交收到 409，資料庫無新增');
    await one.unroute('**/api/state', block);
    await Promise.all([one,two].map(p => p.getByText('活動階段：已結束').waitFor()));
    for(const p of [teacher,one,two]) {
      await q2(p).getByText('無作答').waitFor();
      const result = await q1(p).innerText();
      assert.match(result,/第 1 名（搶答成功）\s*·\s*第 1 組：第一組答案/);
      assert.match(result,/第 2 名\s*·\s*第 2 組：第二組答案/);
    }
    await teacher.screenshot({path:path.join(evidence,'teacher-results.png'), fullPage:true});
    await one.screenshot({path:path.join(evidence,'student-results.png'), fullPage:true});
    step('恢復輪詢並驗證三個結果畫面、順位及無作答');
    console.log('瀏覽器驗收通過（自動化，非人工驗收）');
  } finally {
    if(browser) await browser.close();
    if (server.exitCode === null) {
      const exited = new Promise(resolve => server.once('exit', resolve));
      server.kill();
      await exited;
    }
    if (fs.existsSync(db)) fs.unlinkSync(db);
    fs.rmdirSync(temp);
  }
}
run().catch(error => { console.error(error); process.exitCode=1; });
