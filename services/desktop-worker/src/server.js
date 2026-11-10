'use strict';
const http=require('node:http');
const fs=require('node:fs');
const crypto=require('node:crypto');
const {Jobs}=require('./jobs');
const {settings}=require('./settings');
const {createChatGPTBackend,safeArtifact}=require('./chatgpt');
function createServer(config,execute=createChatGPTBackend(config)) {
  const jobs=new Jobs(config,execute);
  const server=http.createServer(async(req,res)=>{
    const json=(status,data)=>{res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});res.end(JSON.stringify(data));};
    const expected=Buffer.from('Bearer '+config.token),given=Buffer.from(String(req.headers.authorization||''));
    if(given.length!==expected.length||!crypto.timingSafeEqual(given,expected))return json(401,{error:'Unauthorized'});
    const url=new URL(req.url,'http://worker');
    try{
      if(req.method==='GET'&&url.pathname==='/health')return json(200,{backend:config.backend,queue_ready:!jobs.blocked,window_status:'not_checked',blocked:jobs.blocked,running:jobs.running,queued:jobs.queue.length});
      if(req.method==='POST'&&url.pathname==='/v1/reset'){jobs.reset();return json(200,{reviewed:true});}
      if(req.method==='POST'&&url.pathname==='/v1/tasks'){
        if(!String(req.headers['content-type']).startsWith('application/json'))return json(415,{error:'Expected application/json'});
        const chunks=[];let bytes=0;
        for await(const chunk of req){bytes+=chunk.length;if(bytes>42*1024*1024)return json(413,{error:'Task request too large'});chunks.push(chunk);}
        let body;try{body=JSON.parse(Buffer.concat(chunks).toString('utf8'));}catch{return json(400,{error:'Invalid JSON'});}
        return json(202,jobs.enqueue(body));
      }
      const match=/^\/v1\/tasks\/([a-zA-Z0-9_-]{16,80})(?:\/artifacts\/([\w-]+))?$/.exec(url.pathname);
      if(req.method==='GET'&&match){
        if(!match[2]){const job=jobs.get(match[1]);return json(job?200:404,job||{error:'Task not found'});}
        const artifact=jobs.artifact(match[1],match[2]);if(!artifact)return json(404,{error:'Artifact not found'});
        const real=safeArtifact(config.state,artifact.path,20*1024*1024);
        if(crypto.createHash('sha256').update(fs.readFileSync(real)).digest('hex')!==artifact.sha256)throw Error('Artifact changed after capture');
        res.writeHead(200,{'Content-Type':'application/octet-stream','Content-Length':artifact.bytes,'Cache-Control':'no-store'});
        const stream=fs.createReadStream(real);stream.on('error',()=>res.destroy());stream.pipe(res);return;
      }
      return json(404,{error:'Not found'});
    }catch(error){if(!res.headersSent)json(error.status||400,{error:String(error.message).split(config.token).join('[redacted]').slice(0,400)});else res.destroy();}
  });
  server.headersTimeout=10000;server.requestTimeout=30000;server.keepAliveTimeout=5000;
  return {server,jobs};
}
if(require.main===module){
  try{
    const config=settings();
    const {server}=createServer(config);
    server.once('error',error=>{console.error('Desktop worker failed: '+error.code);process.exitCode=1;});
    server.listen(config.port,config.listen_host,()=>console.log(JSON.stringify({event:'desktop-worker.ready',port:config.port,backend:config.backend})));
    for(const signal of ['SIGINT','SIGTERM'])process.on(signal,()=>{server.close();process.exit(0);});
  }catch(error){console.error(error.message);process.exitCode=1;}
}
module.exports={createServer};
