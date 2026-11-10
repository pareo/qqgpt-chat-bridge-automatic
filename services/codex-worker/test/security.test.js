const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const {ACP,execute,searchOptions,searchPrompt}=require('../src/acp');
const {normalize,Jobs}=require('../src/jobs');
const {safeArtifact}=require('../src/artifacts');
test('permission requests are denied rather than approved',()=>{
 const messages=[],client=Object.create(ACP.prototype);client.send=message=>messages.push(message);
 client.receive({id:1,method:'session/request_permission',params:{options:[{optionId:'approve',kind:'allow_always'}]}});
 assert.deepEqual(messages[0].result,{outcome:{outcome:'cancelled'}});
});
test('filesystem, terminal and unknown RPCs are unavailable',()=>{
 const client=Object.create(ACP.prototype);client.send=message=>assert.equal(message.error.code,-32601);
 for(const method of ['fs/read_text_file','fs/write_text_file','terminal/create','authenticate'])client.receive({id:1,method});
});
test('task payload cannot supply command, cwd, model, auth or recipient',()=>{
 const task=normalize({id:'abcdefghijklmnop',kind:'chat',prompt:'hello',cwd:'/host',command:'shell',token:'leak',group:'other',model:'override'});
 assert.deepEqual(Object.keys(task).sort(),['id','images','kind','prompt']);
 assert.throws(()=>normalize({...task,id:'../../sensitive'}));
});
test('abnormal stop is not accepted as a complete response',async t=>{
 const root=path.resolve(__dirname,'../../../data/codex-tests');fs.mkdirSync(root,{recursive:true});
 const state=fs.mkdtempSync(path.join(root,'test-'));
 t.after(()=>{if(path.dirname(state)!==root)throw Error('Unsafe cleanup');fs.rmSync(state,{recursive:true,force:true});});
 const connect=()=>({request:async method=>method==='session/new'?{sessionId:'session'}:method==='session/prompt'?{stopReason:'max_tokens'}:{},close:()=>{}});
 await assert.rejects(execute({id:'abcdefghijklmnop',kind:'chat',prompt:'test',images:[]},{checkpoint:()=>{}},{state,timeout_seconds:30},connect),/did not complete/);
 assert.throws(()=>safeArtifact(state,__filename,100000));
});
test('worker imports no GUI, clipboard or desktop adapter',()=>{
 for(const file of ['acp.js','main.js','server.js'])assert.doesNotMatch(fs.readFileSync(path.join(__dirname,'../src',file),'utf8'),/createChatGPTBackend|desktop-worker|app\.prepare|Clipboard/);
});
test('container has no host source, QQ state, Docker socket or main secrets mounts',()=>{
 const text=fs.readFileSync(path.join(__dirname,'../../../compose.codex.yaml'),'utf8');
 assert.match(text,/read_only: true/);assert.match(text,/no-new-privileges/);assert.match(text,/cap_drop: \[ALL\]/);
 assert.doesNotMatch(text,/docker\.sock|config\/local|data\/qq|privileged: true/);
});
test('search has a bounded retrieval brief and configurable effort',()=>{
 assert.deepEqual(searchOptions({reasoning_effort:'high'}),{effort:'low',rounds:2});
 assert.deepEqual(searchOptions({search_reasoning_effort:'medium',search_max_rounds:3}),{effort:'medium',rounds:3});
 assert.throws(()=>searchOptions({search_max_rounds:0}));
 assert.throws(()=>searchOptions({search_reasoning_effort:'bogus'}));
 assert.match(searchPrompt({}),/最多2轮/);assert.match(searchPrompt({}),/核验限制/);
});
test('search uses its own effort without changing chat or image settings',async t=>{
 const root=path.resolve(__dirname,'../../../data/codex-tests');fs.mkdirSync(root,{recursive:true});
 const state=fs.mkdtempSync(path.join(root,'effort-'));
 t.after(()=>{if(path.dirname(state)!==root)throw Error('Unsafe cleanup');fs.rmSync(state,{recursive:true,force:true});});
 const efforts=[];
 const connect=(cfg,notify)=>{
  efforts.push(cfg.reasoning_effort);
  return {request:async(method,params)=>{
   if(method==='session/new')return {sessionId:'session'};
   if(method==='session/prompt'){
    notify({sessionId:'session',update:{sessionUpdate:'agent_message_chunk',content:{type:'text',text:'Verified evidence'}}});
    return {stopReason:'end_turn'};
   }
   return {};
  },close:()=>{}};
 };
 for(const kind of ['search','chat']){
  const result=await execute({id:'abcdefghijklmnop-'+kind,kind,prompt:'test',images:[]},{checkpoint:()=>{}},{state,reasoning_effort:'medium',timeout_seconds:30},connect);
  assert.equal(result.text,'Verified evidence');assert.ok(result.timings.total_ms>=result.timings.setup_ms);
 }
 assert.deepEqual(efforts,['low','medium']);
});
