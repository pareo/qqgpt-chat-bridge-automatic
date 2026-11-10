'use strict';
const {spawn} = require('node:child_process');
const readline = require('node:readline');
const ALLOWED = new Set(['app.inspect','app.prepare','app.state','app.copyReply','app.fill','app.attachFile','app.attachImage','app.captureImages','app.captureFiles','app.submit','quit']);
class Native {
  constructor(config) {
    this.pending = new Map(); this.next = 0; this.closed = false;
    this.child = spawn(config.binary,[],{windowsHide:true,stdio:['pipe','pipe','pipe'],env:{...process.env,DAIFEILONG_WORKER_STATE_DIR:config.state}});
    readline.createInterface({input:this.child.stdout}).on('line',line=>{
      let message; try {message=JSON.parse(line.replace(/^\uFEFF/,''));} catch {return;}
      const item=this.pending.get(message.id); if (!item) return;
      clearTimeout(item.timer);this.pending.delete(message.id);
      message.ok?item.resolve(message.data):item.reject(Object.assign(Error(message.error),{commitAttempted:message.commitAttempted,draftTouched:message.draftTouched}));
    });
    // Stderr is deliberately not forwarded: accessibility data can be private.
    this.child.stderr.resume();
    this.child.once('error',()=>this.fail(Error('ChatGPT window helper failed to start; run worker-build')));
    this.child.stdin.on('error',()=>this.fail(Error('ChatGPT window helper pipe closed')));
    this.child.once('exit',()=>this.fail(Error('ChatGPT window helper exited')));
  }
  fail(error) {
    this.closed=true;
    for (const item of this.pending.values()) {clearTimeout(item.timer);item.reject(error);}
    this.pending.clear();
  }
  request(op,values={},timeout=30000) {
    if (!ALLOWED.has(op)) return Promise.reject(Error('Forbidden native operation'));
    if (this.closed) return Promise.reject(Error('ChatGPT helper is unavailable'));
    return new Promise((resolve,reject)=>{
      const id=++this.next;
      const timer=setTimeout(()=>{this.fail(Error('Window operation timed out; helper stopped to prevent late actions'));this.child.kill();},timeout);
      this.pending.set(id,{resolve,reject,timer});
      this.child.stdin.write(JSON.stringify({...values,id,op})+'\n');
    });
  }
  close(){this.fail(Error('Worker stopped'));this.child.stdin.end();this.child.kill();}
}
module.exports={Native,ALLOWED};
