'use strict';
const fs=require('node:fs');
const {ACP,execute}=require('./acp');
const config=JSON.parse(fs.readFileSync('/run/worker.json','utf8'));
Object.assign(config,{state:'/state/tasks',cwd:'/state/tasks'});fs.mkdirSync(config.state,{recursive:true});
(async()=>{
 const acp=new ACP(config);
 try{
  const initialized=await acp.request('initialize',{protocolVersion:1,clientInfo:{name:'daifeilong-doctor',version:'0.1.0'},clientCapabilities:{}});
  console.log(JSON.stringify({protocol:initialized.protocolVersion,agent:initialized.agentInfo,capabilities:initialized.agentCapabilities}));
  const session=await acp.request('session/new',{cwd:config.cwd,mcpServers:[]});
  console.log(JSON.stringify({session_created:!!session.sessionId,modes:session.modes,configOptions:session.configOptions}));
 }finally{acp.close();}
})().catch(error=>{const detail=JSON.stringify({error:error.message,details:error.details,diagnostics:error.diagnostics}).replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi,'[email]').replace(/(?:sk-|eyJ)[A-Za-z0-9_.-]{20,}/g,'[credential]');console.error(detail);process.exitCode=1;});
