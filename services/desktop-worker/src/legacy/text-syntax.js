'use strict';
// Keep protocol markers and math delimiters inside Markdown code spans literal.
// A closing backtick run must have exactly the opening length.
function inlineCodeSpans(text){
 const spans=[],runs=[...text.matchAll(/`+/g)];
 for(let i=0;i<runs.length;i++){
  const open=runs[i];let slash=0;for(let at=open.index-1;at>=0&&text[at]==='\\';at--)slash++;
  if(slash%2)continue;
  let end=i+1;while(end<runs.length&&runs[end][0].length!==open[0].length)end++;
  if(end===runs.length)continue;
  spans.push({start:open.index,end:runs[end].index+runs[end][0].length});i=end;
 }
 return spans;
}
function promptTextVariants(text){
 const lines=text.replace(/\r\n?/g,'\n').split('\n'),plain=[],rendered=[];let fence=null,pending=[];
 const flush=()=>{const source=pending.join('\n'),spans=inlineCodeSpans(source);let value='',at=0;for(const span of spans){const count=/^`+/.exec(source.slice(span.start))[0].length;value+=source.slice(at,span.start)+source.slice(span.start+count,span.end-count);at=span.end;}rendered.push(value+source.slice(at));pending=[];};
 for(const line of lines){
  const mark=/^\s*(`{3,}|~{3,})([^\r\n]*)$/.exec(line);
  if(!fence&&mark&&!(mark[1][0]==='`'&&mark[2].includes('`'))){flush();fence=mark[1];continue;}
  if(fence&&mark&&mark[1][0]===fence[0]&&mark[1].length>=fence.length&&!mark[2].trim()){fence=null;continue;}
  plain.push(line);if(fence)rendered.push(line);else pending.push(line);
 }
 flush();return [...new Set([text,plain.join('\n'),rendered.join('\n')])];
}
module.exports={inlineCodeSpans,promptTextVariants};
