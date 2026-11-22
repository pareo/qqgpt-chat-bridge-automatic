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
test('search uses its own effort and image tasks use their own model',async t=>{
 const root=path.resolve(__dirname,'../../../data/codex-tests');fs.mkdirSync(root,{recursive:true});
 const state=fs.mkdtempSync(path.join(root,'effort-'));
 t.after(()=>{if(path.dirname(state)!==root)throw Error('Unsafe cleanup');fs.rmSync(state,{recursive:true,force:true});});
 const selections=[];
 const connect=(cfg,notify)=>{
  selections.push([cfg.model,cfg.reasoning_effort]);
  return {request:async(method,params)=>{
   if(method==='session/new')return {sessionId:'session',configOptions:[{category:'model',currentValue:cfg.model}]};
   if(method==='session/prompt'){
    notify({sessionId:'session',update:{sessionUpdate:'agent_message_chunk',content:{type:'text',text:'Verified evidence'}}});
    if(cfg.model==='image-model')notify({sessionId:'session',update:{sessionUpdate:'tool_call',content:[{type:'content',content:{type:'image',mimeType:'image/png',data:'aW1hZ2U='}}]}});
    return {stopReason:'end_turn'};
   }
   return {};
  },close:()=>{}};
 };
 for(const kind of ['search','chat','image','sticker']){
  const result=await execute({id:'abcdefghijklmnop-'+kind,kind,prompt:'test',images:[]},{checkpoint:()=>{}},{state,model:'general-model',image_model:'image-model',reasoning_effort:'medium',timeout_seconds:30},connect);
  assert.equal(result.text,'Verified evidence');assert.ok(result.timings.total_ms>=result.timings.setup_ms);
 }
 assert.deepEqual(selections,[['general-model','low'],['general-model','medium'],['image-model','medium'],['image-model','medium']]);
});
test('ACP captures GIF image content as a binary artifact',async t=>{
 const root=path.resolve(__dirname,'../../../data/codex-tests');fs.mkdirSync(root,{recursive:true});
 const state=fs.mkdtempSync(path.join(root,'gif-'));
 t.after(()=>{if(path.dirname(state)!==root)throw Error('Unsafe cleanup');fs.rmSync(state,{recursive:true,force:true});});
 const gif=Buffer.from('R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7','base64');
 const connect=(cfg,notify)=>({request:async method=>{
  if(method==='session/new')return {sessionId:'gif'};
  if(method==='session/prompt'){
   notify({sessionId:'gif',update:{sessionUpdate:'agent_message_chunk',content:{type:'image',mimeType:'image/gif',data:gif.toString('base64')}}});
   return {stopReason:'end_turn'};
  }
  return {};
 },close:()=>{}});
 const result=await execute({id:'abcdefghijklmnop',kind:'image',prompt:'GIF example',images:[]},{checkpoint:()=>{}},{state,timeout_seconds:30},connect);
 assert.equal(result.artifacts.length,1);
 assert.equal(path.extname(result.artifacts[0].path),'.gif');
 assert.deepEqual(fs.readFileSync(result.artifacts[0].path),gif);
});
test('image deadline finalizes the isolated job and preserves already returned artifacts',async t=>{
 const root=path.resolve(__dirname,'../../../data/codex-tests');fs.mkdirSync(root,{recursive:true});
 const state=fs.mkdtempSync(path.join(root,'deadline-'));
 t.after(()=>{if(path.dirname(state)!==root)throw Error('Unsafe cleanup');fs.rmSync(state,{recursive:true,force:true});});
 const checkpoints=[];
 const config={state,model:'general-model',timeout_seconds:240,image_timeout_seconds:420};
 const connect=(withImage)=>(cfg,notify)=>({request:async(method,params,timeout)=>{
  if(method==='session/new')return {sessionId:'img'};
  if(method==='session/prompt'){
   assert.equal(timeout,420000);
   if(withImage)notify({sessionId:'img',update:{sessionUpdate:'tool_call',content:{type:'image',mimeType:'image/png',data:'aW1hZ2U='}}});
   throw Object.assign(Error('ACP timeout; no automatic replay'),{code:'ACP_DEADLINE'});
  }
  return {};
 },close:()=>{}});
 const context={checkpoint:state=>checkpoints.push(state)};
 const task={id:'abcdefghijklmnop',kind:'image',prompt:'test',images:[]};
 await assert.rejects(execute(task,context,config,connect(false)),{code:'image_generation_timeout',uncertain:false});
 assert.deepEqual(checkpoints,['submitting','image_deadline_reached']);
 const result=await execute({...task,id:'abcdefghijklmnoq'},context,config,connect(true));
 assert.equal(result.artifacts.length,1);
 assert.equal(checkpoints.at(-1),'result_received');
});

test('a legacy isolated image deadline does not latch the worker on restart',t=>{
 const root=path.resolve(__dirname,'../../../data/codex-tests');fs.mkdirSync(root,{recursive:true});
 const state=fs.mkdtempSync(path.join(root,'recovery-'));
 t.after(()=>{if(path.dirname(state)!==root)throw Error('Unsafe cleanup');fs.rmSync(state,{recursive:true,force:true});});
 const jobsDir=path.join(state,'jobs');fs.mkdirSync(jobsDir);
 const id='abcdefghijklmnop';
 const old={id,kind:'image',state:'uncertain',error:'ACP timeout; no automatic replay'};
 fs.writeFileSync(path.join(jobsDir,id+'.json'),JSON.stringify(old));
 const worker=new Jobs({state},()=>{});
 assert.equal(worker.blocked,false);
 assert.equal(worker.get(id).state,'failed');
 assert.equal(worker.get(id).error_code,'image_generation_timeout');
 const reloaded=new Jobs({state},()=>{});
 assert.equal(reloaded.blocked,false);
 assert.equal(reloaded.get(id).state,'failed');
});
