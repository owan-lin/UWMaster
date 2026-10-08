// Run with node tests_frontend.cjs. No production files or HTTP writes.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const nodes = new Map();
const node = selector => {
  if (!nodes.has(selector)) nodes.set(selector, {disabled:false, scrollTop:0,scrollLeft:0,scrollIntoView(){}, focus(){}});
  return nodes.get(selector);
};
const context = vm.createContext({
  console, URL, Intl, Date, Set,
  window:{scrollX:0,scrollY:400,scrollTo({left,top}){this.scrollX=left;this.scrollY=top}},
  document:{querySelector:node,querySelectorAll:selector=>selector==='.todo-scroll'?[node(selector)]:[],addEventListener(){}},
  fetch:()=>new Promise(()=>{}),
});
vm.runInContext(fs.readFileSync('app.js','utf8'),context);
const run = source => vm.runInContext(source,context);
run(`render=()=>{};
S={courses:[{id:'c',code:'CSE'},{id:'m',code:'MATH'}],tasks:[
 {id:'pending',course_id:'c',title:'Homework',kind:'homework',due:new Date(Date.now()+86400000).toISOString(),certainty:'verified',user_completed:false,user_note:'keep this note'},
 {id:'old',course_id:'c',title:'Old class',kind:'class',is_class:true,due:'2020-01-01T10:00:00-08:00',user_completed:true},
 {id:'other',course_id:'m',title:'Math quiz',kind:'quiz',due:null,user_completed:true},
 {id:'scored',course_id:'c',title:'Scored task',kind:'homework',due:null,source_status:'scored',user_completed:false},
 {id:'ed',course_id:'c',title:'Ed material',kind:'preparation',due:null,source_status:'completed',user_completed:false}
]};`);
const ids = expression => Array.from(run(expression),x=>x.id);
assert.equal(run("seattleTaskDate('2026-10-09','15:30')"),'2026-10-09T22:30:00.000Z');
assert.equal(run("seattleTaskDate('2026-11-02','09:00')"),'2026-11-02T17:00:00.000Z');
assert.equal(run("seattleTaskDate('2026-11-02','')"),'2026-11-02');
assert.throws(()=>run("seattleTaskDate('2026-03-08','02:30')"));
assert.deepEqual(ids('completedList()'),['old','other']);
assert.deepEqual(ids('list()'),['pending']);
run("course='c';search='old'");
assert.deepEqual(ids('completedList()'),['old']);
run("course='all';search='';filter='all'");
assert.equal(ids('list()').length,5);
assert.deepEqual(ids('list().filter(x=>x.user_completed)'),['old','other']);
run("filter='done'");
assert.deepEqual(ids('list()'),['old','other']);

async function checkState(){
  run("filter='week';fetch=async(url,options)=>{globalThis.body=JSON.parse(options.body);return {ok:true}};");
  assert.equal(await run("state('pending',true)"),true);
  assert.equal(run('completedOpen'),true);
  assert.equal(run('stateNotice'),null);
  assert.equal(run('body.note'),'keep this note');
  assert(!ids('list()').includes('pending'));
  assert(ids('completedList()').includes('pending'));
  assert.equal(await run("state('pending',false)"),true);
  assert(ids('list()').includes('pending'));
  assert.equal(await run("state('old',false)"),true);
  assert.equal(run('stateNotice'),null);
  assert.equal(run("S.tasks.find(x=>x.id==='old').user_completed"),false);

  // A rejected save must leave the task and note unchanged.
  run("fetch=async()=>({ok:false,json:async()=>({error:'test rejection'})})");
  assert.equal(await run("state('pending',true)"),false);
  assert.equal(run("S.tasks[0].user_completed"),false);
  assert.equal(run("S.tasks[0].user_note"),'keep this note');
  assert.equal(run('stateNotice.error'),true);
  run("fetch=async()=>{throw Error('offline')}");
  assert.equal(await run("state('pending',true)"),false);
  assert.equal(run('pendingStates.size'),0);

  // Delay the request: duplicate completion and undo must not submit twice.
  run("globalThis.requests=0;fetch=()=>{requests++;return new Promise(resolve=>{globalThis.finishSave=resolve})}");
  const saving=run("state('pending',true)");
  assert.equal(run("pendingStates.has('pending')"),true);
  assert.equal(await run("state('pending',true)"),false);
  assert.equal(await run("state('pending',false)"),false);
  assert.equal(run('requests'),1);
  assert(run('card(S.tasks[0])').includes('disabled'));
  run('finishSave({ok:true})');
  assert.equal(await saving,true);
  assert.equal(run('pendingStates.size'),0);

  // Saving a note must not create a completion event or expand the section.
  run("completedOpen=false;stateNotice=null;fetch=async()=>({ok:true})");
  assert.equal(await run("state('pending',true)"),true);
  assert.equal(run('completedOpen'),false);
  assert.equal(run('stateNotice'),null);
  // Rerendering may reset panel scroll; the save must restore it.
  node('.todo-scroll').scrollTop=240;
  node('.todo-scroll').scrollLeft=15;
  run("render=()=>{document.querySelector('.todo-scroll').scrollTop=0;document.querySelector('.todo-scroll').scrollLeft=0;window.scrollY=0};");
  assert.equal(await run("state('pending',false)"),true);
  assert.equal(node('.todo-scroll').scrollTop,240);
  assert.equal(node('.todo-scroll').scrollLeft,15);
  assert.equal(run('window.scrollY'),400);
  assert.equal(run('stateNotice'),null);
  console.log('PASS completion, restore, filtering, failure, duplicate-save and stable-scroll regressions');
}
checkState().catch(error=>{console.error(error);process.exitCode=1});
