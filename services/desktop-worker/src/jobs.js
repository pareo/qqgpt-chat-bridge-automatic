'use strict';
const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');
const TERMINAL=new Set(['succeeded','failed','uncertain']);
function normalize(input) {
  if(!input||typeof input!=='object'||Array.isArray(input))throw Error('Invalid task');
  if(typeof input.id!=='string'||!/^[a-zA-Z0-9_-]{16,80}$/.test(input.id))throw Error('Invalid task ID');
  if(!['search','image','sticker'].includes(input.kind))throw Error('Invalid task kind');
  if(typeof input.prompt!=='string'||!input.prompt.trim()||input.prompt.length>18000)throw Error('Prompt must contain 1..18000 characters');
  if(input.images!==undefined&&!Array.isArray(input.images))throw Error('images must be an array');
  if((input.images||[]).length>4)throw Error('At most four reference images');
  let total=0;
  const images=(input.images||[]).map(item=>{
    if(typeof item?.base64!=='string'||item.base64.length>14*1024*1024||item.base64.length%4||!/^[A-Za-z0-9+/]*={0,2}$/.test(item.base64))throw Error('Invalid image encoding');
    const raw=Buffer.from(item.base64,'base64');total+=raw.length;
    if(raw.toString('base64')!==item.base64)throw Error('Noncanonical image encoding');
    if(!raw.length||raw.length>10*1024*1024||total>30*1024*1024)throw Error('Reference images exceed the size limit');
    const extension=raw.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10]))?'.png':raw[0]===255&&raw[1]===216&&raw[2]===255?'.jpg':raw.toString('ascii',0,4)==='RIFF'&&raw.toString('ascii',8,12)==='WEBP'?'.webp':'';
    if(!extension)throw Error('Reference must be a PNG, JPEG or WebP image');
    return {extension,base64:raw.toString('base64')};
  });
  return {id:input.id,kind:input.kind,prompt:input.prompt.trim(),images};
}
function atomic(file,data) {fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file+'.tmp',JSON.stringify(data));fs.renameSync(file+'.tmp',file);}
class Jobs {
  constructor(config,execute) {
    this.config=config;this.execute=execute;this.jobs=new Map();this.queue=[];this.running=false;this.blocked=false;
    this.root=path.join(config.state,'jobs');fs.mkdirSync(this.root,{recursive:true});
    for(const name of fs.readdirSync(this.root).filter(n=>/^[\w-]+\.json$/.test(n))){
      const job=JSON.parse(fs.readFileSync(path.join(this.root,name),'utf8'));
      if(!TERMINAL.has(job.state)){
        job.state=['submitting','awaiting_result'].includes(job.state)?'uncertain':'failed';
        job.error='Worker restarted before completion; task was not replayed';job.updated_at=new Date().toISOString();
        this.save(job);
      }
      if(job.state==='uncertain'&&!job.reviewed)this.blocked=true;
      this.jobs.set(job.id,job);
    }
  }
  save(job){atomic(path.join(this.root,job.id+'.json'),job);}
  enqueue(input){
    const task=normalize(input),digest=crypto.createHash('sha256').update(JSON.stringify(task)).digest('hex');
    const existing=this.jobs.get(task.id);
    if(existing){if(existing.digest!==digest)throw Object.assign(Error('Task ID already used for different content'),{status:409});return this.public(existing);}
    if(this.blocked)throw Object.assign(Error('Previous desktop submission is uncertain; review the dedicated ChatGPT session and run worker-reset'),{status:409});
    if(this.queue.length+(this.running?1:0)>=this.config.max_queue)throw Object.assign(Error('Desktop task queue is full; ordinary API chat remains available'),{status:429});
    const job={...task,digest,state:'queued',created_at:new Date().toISOString(),updated_at:new Date().toISOString()};
    this.save(job);this.jobs.set(job.id,job);this.queue.push(job.id);queueMicrotask(()=>this.drain());return this.public(job);
  }
  public(job){return {id:job.id,kind:job.kind,state:job.state,created_at:job.created_at,updated_at:job.updated_at,...(job.error?{error:job.error}:{}),...(job.result?{result:{...job.result,artifacts:job.result.artifacts.map(({path,...item})=>item)}}:{})};}
  get(id){const job=this.jobs.get(id);return job?this.public(job):null;}
  artifact(id,artifactId){return this.jobs.get(id)?.result?.artifacts.find(a=>a.id===artifactId);}
  checkpoint(job,state){job.state=state;job.updated_at=new Date().toISOString();this.save(job);}
  async drain(){
    if(this.running||this.blocked)return;this.running=true;
    try{
      while(this.queue.length&&!this.blocked){
        const job=this.jobs.get(this.queue.shift());this.checkpoint(job,'running');
        try{
          const result=await this.execute(job,{checkpoint:state=>this.checkpoint(job,state)});
          const artifacts=result.artifacts.map(item=>({...item,id:crypto.randomUUID(),sha256:crypto.createHash('sha256').update(fs.readFileSync(item.path)).digest('hex'),bytes:fs.statSync(item.path).size}));
          job.result={text:String(result.text||'').slice(0,150000),backend:result.backend,artifacts};this.checkpoint(job,'succeeded');
        }catch(error){
          job.error=String(error.message||'Task failed').split(this.config.token).join('[redacted]').slice(0,400);
          const uncertain=error.uncertain||['submitting','awaiting_result'].includes(job.state);
          this.checkpoint(job,uncertain?'uncertain':'failed');this.blocked=!!uncertain;
          if(this.blocked){
            for(const id of this.queue.splice(0)){const queued=this.jobs.get(id);queued.error='Desktop queue stopped for an uncertain previous submission';this.checkpoint(queued,'failed');}
          }
        }
      }
    }finally{this.running=false;}
  }
  reset(){
    if(this.running)throw Object.assign(Error('A task is still running'),{status:409});
    for(const job of this.jobs.values())if(job.state==='uncertain'){job.reviewed=true;this.save(job);}
    this.blocked=false;
  }
}
module.exports={Jobs,normalize,TERMINAL};
