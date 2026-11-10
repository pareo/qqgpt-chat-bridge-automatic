'use strict';
const { walk } = require('./tree');
const { inlineCode, renderBody, tableData } = require('./reply-format');
const {promptTextVariants}=require('./text-syntax');
const {codeWidget}=require('./source-blocks');

function extractAppResponse(tree, prompt, options = {}) {
  const empty = () => ({ reply: '', content: [], complete: false });
  let region;
  walk(tree, n => { if (!region && (n.role === 16 || n.role === 20) && /^(对话|Conversation)$/.test(n.name || '')) region = n; });
  if (!region) return empty();
  // The native tree includes the disclaimer and composer as siblings of the transcript.
  // Descend through single wrappers to the common list containing the user/assistant headings.
  const headers = new WeakMap();
  function hasHeading(n) { if (headers.has(n)) return headers.get(n); const found = n.role === 20 && /^(你说：|You said:|ChatGPT 说：|ChatGPT said:)$/.test(n.name || '') || (n.children || []).some(hasHeading); headers.set(n, found); return found; }
  while (true) { const branches = (region.children || []).filter(hasHeading); if (branches.length !== 1 || branches[0].role===20&&/^(你说：|You said:|ChatGPT 说：|ChatGPT said:)$/.test(branches[0].name||'')) break; region = branches[0]; }
  const tokens = [], compact = s => s.replace(/\s+/gu, '');
  let visible = '', turn = '',codeIndex=0,mathIndex=0;
  function visit(n, parents = []) {
    const name = n.name || '';
    if(n.role===8){
      const alert=[];walk(n,child=>{if(child.role===41)alert.push(child.name||'');});
      if(/cloudflare|cf_chl|cf-chl|challenge-platform/i.test(alert.join(' '))){tokens.push({kind:'client-error',offset:visible.length});return;}
    }
    if(options.mathImages&&turn==='assistant'&&n.role===55){
      const source=n.value||n.name;
      if(source){mathIndex++;tokens.push({kind:'math',source,offset:visible.length});return;}
      tokens.push({kind:'math-source',index:mathIndex++,offset:visible.length});return;
    }
    if(turn==='assistant'){const code=codeWidget(n);if(code){tokens.push({kind:'code-source',...code,index:codeIndex++,offset:visible.length});return;}}
    if(options.tableImages&&turn==='assistant'&&n.role===24){
      let assets=false;walk(n,child=>{if(child.mediaRef||child.fileRef)assets=true;});
      const table=!assets&&tableData(n);
      if(table){tokens.push({...table,offset:visible.length});return;}
    }
    if(n.fileRef){tokens.push({kind:'file',ref:n.fileRef,name:n.fileName,offset:visible.length});return;}
    if (n.role === 57 || n.role === 42 && !(['user','assistant'].includes(turn) && inlineCode(n))) return;
    if (n.role === 33 && /^(轮播列表|Carousel|Carousel list)$/i.test(name)) {
      let hasImage=false;walk(n,child=>{if(child.role===40&&child.mediaRef)hasImage=true;});
      if(!hasImage)tokens.push({kind:'pending-media',offset:visible.length});
    }
    if (n.role === 43) {
      if (/^(复制消息|Copy message)$/.test(name)) tokens.push({ kind: 'user-end', offset: visible.length });
      if (/^(复制|复制回复|Copy|Copy response)$/.test(name)) tokens.push({ kind: 'copy', offset: visible.length });
      if (/^(下载|保存图像|保存图片|Download|Save image|复制图像|复制图片|Copy image)$/.test(name)) tokens.push({ kind: 'image-ready', offset: visible.length });
      function images(child) { if (child.role === 40 && child.mediaRef) tokens.push({ kind: 'image', ref: child.mediaRef, alt: child.name, offset: visible.length }); else for (const nested of child.children || []) images(nested); }
      for (const child of n.children || []) images(child);
      return;
    }
    if (n.role === 40 && n.mediaRef) { tokens.push({ kind: 'image', ref: n.mediaRef, alt: name, offset: visible.length }); return; }
    if (n.role === 20 && /^(你说：|You said:|ChatGPT 说：|ChatGPT said:)$/.test(name)) {
      turn = /^(ChatGPT)/.test(name) ? 'assistant' : 'user';
      if(turn==='assistant'){codeIndex=0;mathIndex=0;}
      tokens.push({ kind: turn, offset: visible.length }); return;
    }
    if (n.role === 41 || [25, 26, 29, 30, 34].includes(n.role) && !(n.children || []).length) {
      tokens.push({ kind: 'text', text: name, node: n, parents, offset: visible.length }); visible += compact(name); return;
    }
    for (const child of n.children || []) visit(child, [...parents, n]);
  }
  visit(region);
  const userIndex=tokens.findLastIndex(t=>t.kind==='user'),user=tokens[userIndex];
  if(!user)return empty();
  const end=tokens.slice(userIndex+1).find(t=>['user-end','assistant'].includes(t.kind))?.offset??visible.length;
  let needle='',at=-1;
  for(const variant of promptTextVariants(prompt)){
    const candidate=compact(variant),index=candidate?visible.lastIndexOf(candidate,end-candidate.length):-1;
    if(index>=user.offset&&index+candidate.length<=end&&index>at){needle=candidate;at=index;}
  }
  if (at < 0) return empty();
  if (tokens.filter(t => t.kind === 'user').at(-1)?.offset > at) return empty();
  const userEndIndex=tokens.findIndex((t,i)=>i>userIndex&&t.kind==='user-end');
  if(userEndIndex>=0&&tokens.slice(userEndIndex+1).some(t=>t.kind==='client-error'))return {...empty(),clientError:'AI聊天遇到Cloudflare验证或访问限制，请在客户端处理后重试。'};
  const headings = tokens.map((token, index) => ({ ...token, index })).filter(t => t.kind === 'assistant' && t.offset >= at + needle.length);
  const heading = headings.at(-1); if (!heading) return empty();
  const body = [], content = []; let runs = [], complete = false, pendingMedia = false;
  const flush = () => { const text = renderBody(runs); if (text) content.push({ kind: 'text', text }); runs = []; };
  // Generated assets can precede the assistant heading in the native transcript.
  // The user's copy-message control closes their turn, so images after that
  // control and before the assistant heading belong to this response. Never
  // collect user attachments or assets from an earlier exchange.
  const userEnd = tokens.map((token, index) => ({ ...token, index })).filter(t =>
    t.kind === 'user-end' && t.offset >= at + needle.length && t.index < heading.index).at(-1);
  if (userEnd) for (const token of tokens.slice(userEnd.index + 1, heading.index)) {
    if (token.kind === 'pending-media') pendingMedia = true;
    if (token.kind === 'image' && !content.some(c => c.ref === token.ref))
      content.push({ kind: 'image', ref: token.ref, alt: token.alt });
    if (token.kind === 'file' && !content.some(c => c.ref === token.ref))
      content.push({ kind: 'file', ref: token.ref, name: token.name });
  }
  for (const token of tokens.slice(heading.index + 1)) {
    if (token.kind === 'pending-media') pendingMedia = true;
    if (token.kind === 'copy') { complete = true; break; }
    if (token.kind === 'image-ready') { complete = true; continue; }
    if (token.kind === 'user' || token.kind === 'assistant') return empty();
    if (token.kind === 'image') { flush(); if (!content.some(c => c.ref === token.ref)) content.push({ kind: 'image', ref: token.ref, alt: token.alt }); }
    if (token.kind === 'file') { flush(); if (!content.some(c => c.ref === token.ref)) content.push({ kind: 'file', ref: token.ref, name: token.name }); }
    if (token.kind === 'table') { flush();content.push({kind:'table',rows:token.rows,hasHeader:token.hasHeader}); }
    if (token.kind === 'math') { flush();content.push({kind:'math',source:token.source}); }
    if (token.kind === 'code-source'||token.kind==='math-source') {flush();const {offset,...part}=token;content.push(part);}
    if (token.kind === 'text') { body.push(token); runs.push(token); }
  }
  if (!complete) return empty();
  flush(); return { reply: options.tableImages||options.mathImages?content.filter(p=>p.kind==='text').map(p=>p.text).join('\n\n'):renderBody(body), content, complete: !pendingMedia, ...(pendingMedia?{pendingMedia:true}:{}) };
}
function extractAppReply(tree, prompt) { return extractAppResponse(tree, prompt).reply; }

module.exports = { extractAppReply, extractAppResponse };
