'use strict';
const language=value=>String(value||'').trim().split(/\s/)[0].toLowerCase().replace(/^csharp$/,'c#').replace(/^tex$/,'latex');
function codeWidget(node){
 const children=node.children||[],headers=children.filter(child=>(child.children||[]).some(n=>n.role===43&&/^(复制代码|Copy code)$/.test(n.name||'')));
 if(headers.length!==1||children.length<2)return null;
 const header=headers[0],body=children.filter(n=>n!==header);let label='';
 function visit(n){if([43,57].includes(n.role))return;if(n.role===41)label+=n.name||'';else for(const c of n.children||[])visit(c);}visit(header);
 const info=language(label);if(!info||!/^[\w.+#/-]+$/.test(info)||!body.length)return null;
 let preview='',renderedMath=false;
 function source(n){if([43,57].includes(n.role))return;if(n.role===55){renderedMath=true;return;}if(n.role===41)preview+=n.name||'';else for(const c of n.children||[])source(c);}for(const node of body)source(node);
 return {language:info,...(!renderedMath&&preview?{preview}:{})};
}

module.exports={codeWidget};
