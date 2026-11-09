'use strict';
const fs = require('node:fs');
const path = require('node:path');
const ROOT = path.resolve(__dirname, '../../..');
function settings() {
  const load = name => JSON.parse(fs.readFileSync(path.join(ROOT,'config/local',name+'.json'),'utf8').replace(/^\uFEFF/,''));
  const config = load('project'), secrets = load('secrets');
  const worker = config.desktop_worker || {};
  const token = secrets.desktop_worker_token || '';
  if (token.length < 32) throw Error('Set desktop_worker_token to a random token of at least 32 characters in config/local/secrets.json');
  if (!worker.enabled) throw Error('desktop_worker.enabled is false');
  const result = {backend:'chatgpt-app',listen_host:'127.0.0.1',port:18120,conversation_title:'大肥龙工具',model:'current',reasoning_effort:'current',timeout_seconds:240,poll_ms:700,max_queue:4,...worker};
  if (result.backend !== 'chatgpt-app') throw Error('Unsupported worker backend; only chatgpt-app is implemented');
  if (!['127.0.0.1','0.0.0.0'].includes(result.listen_host)) throw Error('listen_host must be 127.0.0.1 or 0.0.0.0');
  if (!Number.isInteger(result.port)||result.port<1024||result.port>65535) throw Error('Invalid worker port');
  if (!Number.isInteger(result.timeout_seconds)||result.timeout_seconds<30||result.timeout_seconds>600) throw Error('Worker timeout must be 30..600 seconds');
  if (!Number.isInteger(result.poll_ms)||result.poll_ms<250||result.poll_ms>5000) throw Error('Worker poll_ms must be 250..5000');
  if (!Number.isInteger(result.max_queue)||result.max_queue<1||result.max_queue>16) throw Error('max_queue must be 1..16');
  if (!result.conversation_title.trim()) throw Error('Dedicated ordinary ChatGPT conversation_title is required');
  if (!['current','low','medium','high'].includes(result.reasoning_effort)) throw Error('Unsupported desktop thinking setting');
  return {...result,token,state:path.join(ROOT,'data/desktop-worker'),binary:path.resolve(__dirname,'../bin/ChatGPTWorker.exe')};
}
module.exports={ROOT,settings};
