const $ = id => document.getElementById(id);
let current = null, busy = false;
async function call(url, data) {
  const response = await fetch(url, {method: data === undefined ? 'GET' : 'POST', headers: {'Content-Type':'application/json'}, body: data === undefined ? undefined : JSON.stringify(data), cache:'no-store'});
  const result = await response.json(); if (!response.ok) throw new Error(result.error || '操作失敗'); return result;
}
function message(text) { $('notice').textContent = text; }
async function run(fn) { try { message(''); await fn(); await refresh(); } catch(e) { message(e.message); } }
document.querySelectorAll('[data-role]').forEach(button => button.onclick = () => run(async () => { const body={role:button.dataset.role}; if(button.dataset.team) body.team=Number(button.dataset.team); await call('/api/join',body); $('join').hidden=true; $('activity').hidden=false; }));
$('change').onclick=()=>{ $('activity').hidden=true; $('join').hidden=false; current=null; };
$('load').onclick=()=>run(async()=>{ const value=$('numbers').value.trim(); if(!/^\d+(\s*,\s*\d+)*$/.test(value)) throw Error('請以逗號分隔正整數題號'); await call('/api/demo',{numbers:value.split(',').map(Number)}); message('已設定測試題目'); });
$('import').onclick=()=>run(async()=>{const result=await call('/api/sheets/import',{spreadsheet:$('sheet').value,confirmed_single_questions:$('confirm-single').checked});message(`已匯入 ${result.count} 題（${result.numbers.join('、')}）；請核對是否漏題。`)});
$('export').onclick=()=>run(async()=>{const result=await call('/api/sheets/export',{});message(`已寫入 ${result.count} 題；請檢查原試算表。`)});
$('start').onclick=()=>run(()=>call('/api/activity/start',{}));
$('end').onclick=()=>run(()=>call('/api/activity/end',{}));
async function refresh(){
 if($('activity').hidden || busy) return; busy=true;
 try { current=await call('/api/state'); render(current); } catch(e){ message('無法更新：'+e.message); } finally { busy=false; }
}
function render(data){
 $('identity').textContent=data.role==='teacher'?'老師':`第 ${data.team} 組`;
 $('phase').textContent='活動階段：'+({ready:'準備中',active:'搶答中',ended:'已結束'}[data.state]);
 $('teacher').hidden=data.role!=='teacher'; $('setup').hidden=data.state!=='ready'; $('start').disabled=data.state!=='ready'; $('end').disabled=data.state!=='active';
 $('export').disabled=data.state!=='ended'||data.source!=='sheets'||!!data.export_status;
 $('source').textContent=data.source==='sheets'?'題目來源：Google Sheets（請核對題數）':'題目來源：本機示範';
 const container=$('questions');
 // Preserve unfinished typing across polling, while never injecting answer HTML.
 const drafts={}; container.querySelectorAll('input[data-question]').forEach(input=>drafts[input.dataset.question]=input.value);
 const focused=document.activeElement?.dataset?.question;
 container.replaceChildren();
 if(!data.questions.length){const p=document.createElement('p');p.textContent='尚未設定題目。';container.append(p);return;}
 for(const q of data.questions){
  const box=document.createElement('article');box.className='question';const title=document.createElement('h3');title.textContent=`第 ${q.number} 題`;box.append(title);
  if(data.role==='student'&&data.state==='active'&&!q.submissions.length){const input=document.createElement('input');input.className='answer';input.placeholder='輸入答案';input.dataset.question=q.id;input.value=drafts[q.id]||'';const button=document.createElement('button');button.textContent='提交答案';button.onclick=()=>run(()=>call('/api/answer',{question_id:q.id,answer:input.value}));box.append(input,document.createTextNode(' '),button);}
  if(q.submissions.length){const list=document.createElement('ul');for(const item of q.submissions){const li=document.createElement('li');li.textContent=(item.rank ? `第 ${item.rank} 名${item.rank===1?'（搶答成功）':''} · ` : '本組已提交 · ')+`${item.team}：${item.answer}`;list.append(li)}box.append(list);} else if(data.state==='ended'){const p=document.createElement('p');p.textContent='無作答';box.append(p)}
  container.append(box);
 }
 if(focused){const input=container.querySelector(`input[data-question="${focused}"]`);if(input){input.focus();input.setSelectionRange(input.value.length,input.value.length)}}
}
setInterval(refresh,1000);
