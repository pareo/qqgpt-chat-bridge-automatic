'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {Jobs,normalize}=require('../src/jobs');
const {createServer}=require('../src/server');
const {ALLOWED}=require('../src/native');
const {makePrompt,safeArtifact}=require('../src/chatgpt');
const {extractAppResponse}=require('../src/legacy/chatgpt');
const tick=()=>new Promise(r=>setImmediate(r));
function setup(t,execute,overrides={}){
 const parent=path.resolve(__dirname,'../../../data/worker-tests');fs.mkdirSync(parent,{recursive:true});
 const state=fs.mkdtempSync(path.join(parent,'test-'));t.after(()=>{if(path.dirname(path.resolve(state))!==parent)throw Error('Unexpected test cleanup path');fs.rmSync(state,{recursive:true,force:true});});
 const config={state,token:'test-token-not-real-'.repeat(3),max_queue:4,backend:'chatgpt-app',...overrides};
 return {config,jobs:new Jobs(config,execute)};
}
const input=(id='abcdefghijklmnop')=>({id,kind:'search',prompt:'test prompt'});
test('queue serializes desktop work and deduplicates accepted IDs',async t=>{
 let active=0,peak=0,calls=0,release;
 const gate=new Promise(r=>release=r);
 const {jobs}=setup(t,async()=>{calls++;peak=Math.max(peak,++active);await gate;active--;return {text:'result',artifacts:[]};});
 jobs.enqueue(input());jobs.enqueue(input());jobs.enqueue(input('qrstuvwxyzabcdef'));
 await tick();assert.equal(calls,1);release();await tick();await tick();
 assert.equal(peak,1);assert.equal(calls,2);assert.equal(jobs.get(input().id).state,'succeeded');
 assert.throws(()=>jobs.enqueue({...input(),prompt:'different'}),/different content/);
});
test('uncertain submission stops queued UI jobs but does not replay generation',async t=>{
 let calls=0;
 const {jobs,config}=setup(t,async(_,context)=>{calls++;context.checkpoint('submitting');throw Error('lost submit result');});
 jobs.enqueue(input());jobs.enqueue(input('qrstuvwxyzabcdef'));await tick();
 assert.equal(calls,1);assert.equal(jobs.get(input().id).state,'uncertain');assert.equal(jobs.blocked,true);
 assert.equal(jobs.get('qrstuvwxyzabcdef').state,'failed');
 const reopened=new Jobs(config,()=>{throw Error('must not execute');});
 assert.equal(reopened.blocked,true);assert.throws(()=>reopened.enqueue(input('newtask1234567890')),/uncertain/);
 reopened.reset();assert.equal(reopened.blocked,false);
 assert.equal(reopened.get(input().id).state,'uncertain');
});
test('restart does not replay interrupted queued or submitted tasks',t=>{
 const {config}=setup(t,async()=>{});
 const base={...input(),digest:'x',state:'awaiting_result'};
 fs.writeFileSync(path.join(config.state,'jobs',base.id+'.json'),JSON.stringify(base));
 const reopened=new Jobs(config,()=>{throw Error('must not run');});
 assert.equal(reopened.get(base.id).state,'uncertain');assert.equal(reopened.queue.length,0);
});
test('invalid tasks, fake images, paths and oversize payloads are rejected',()=>{
 assert.throws(()=>normalize({...input(),id:'../../secret'}));
 assert.throws(()=>normalize({...input(),kind:'shell'}));
 assert.throws(()=>normalize({...input(),images:[{base64:Buffer.from('not an image').toString('base64')}]}));
 assert.throws(()=>normalize({...input(),prompt:'x'.repeat(18001)}));
});
test('QQ, browser and unknown draft operations are absent at both boundaries',()=>{
 for(const op of ['qq.send','qq.snapshot','browser.fill','configure','app.recover','app.discardDraft'])assert.equal(ALLOWED.has(op),false);
 const cs=fs.readFileSync(path.join(__dirname,'../native/Bridge.cs'),'utf8');
 const dispatcher=cs.slice(cs.indexOf('static object Execute('),cs.indexOf('static IAccessible Root('));
 assert.doesNotMatch(dispatcher,/case "(?:qq\.|browser\.|configure|app\.recover)/);
});
test('artifact root confines paths and private paths are omitted from status',async t=>{
 const {config,jobs}=setup(t,async()=>({text:'ok',artifacts:[{kind:'file',name:'a.txt',path:path.join(config.state,'a.txt')}]}));
 fs.writeFileSync(path.join(config.state,'a.txt'),'hello');
 assert.equal(safeArtifact(config.state,path.join(config.state,'a.txt'),10),path.join(config.state,'a.txt'));
 assert.throws(()=>safeArtifact(config.state,__filename,100000));
 jobs.enqueue(input());await tick();
 const item=jobs.get(input().id).result.artifacts[0];assert.equal(item.path,undefined);assert.equal(item.bytes,5);assert.equal(item.sha256.length,64);
});
test('HTTP authenticates task, status and artifact requests',async t=>{
 const {config}=setup(t,async()=>{});
 const worker=createServer(config,async()=>({text:'verified',artifacts:[]}));
 await new Promise(r=>worker.server.listen(0,'127.0.0.1',r));t.after(()=>new Promise(r=>worker.server.close(r)));
 const base='http://127.0.0.1:'+worker.server.address().port;
 assert.equal((await fetch(base+'/health')).status,401);
 const headers={Authorization:'Bearer '+config.token,'Content-Type':'application/json'};
 assert.equal((await fetch(base+'/v1/tasks',{method:'POST',headers,body:JSON.stringify(input())})).status,202);
 await tick();const response=await fetch(base+'/v1/tasks/'+input().id,{headers});
 assert.equal((await response.json()).result.text,'verified');
 assert.equal((await fetch(base+'/v1/tasks/'+input().id+'/artifacts/unknown',{headers})).status,404);
});
test('search and image prompts are independent of sticker instructions',()=>{
 assert.match(makePrompt({...input(),kind:'image'}),/默认高质量/);
 assert.doesNotMatch(makePrompt({...input(),kind:'image'}),/300×300/);
 assert.match(makePrompt({...input(),kind:'sticker'}),/300×300/);
 assert.match(makePrompt({...input(),kind:'search'}),/实际搜索网络/);
});
test('transcript matches the latest question, retains links and ignores earlier replies',()=>{
 const n=(role,name='',children=[],extra={})=>({role,name,children,...extra});
 const tree=n(16,'Conversation',[
  n(20,'You said:'),n(41,'old'),n(43,'Copy message'),n(20,'ChatGPT said:'),n(41,'old answer'),n(43,'Copy'),
  n(20,'You said:'),n(41,'task-unique'),n(43,'Copy message'),n(20,'ChatGPT said:'),
  n(20,'',[n(41,'see '),n(30,'',[n(41,'official docs')],{value:'https://example.com/docs'})]),n(43,'Copy')]);
 const result=extractAppResponse(tree,'task-unique');assert.equal(result.complete,true);
 assert.match(result.reply,/https:\/\/example.com\/docs/);assert.doesNotMatch(result.reply,/old answer/);
 assert.equal(extractAppResponse(tree,'different').complete,false);
});
