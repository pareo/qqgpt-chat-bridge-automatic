'use strict';
function webUrl(value){
 if(typeof value!=='string'||/[\u0000-\u0020\u007f]/u.test(value))return '';
 try{const url=new URL(value);return ['http:','https:'].includes(url.protocol)&&!url.username&&!url.password?value:'';}catch{return '';}
}
function linkText(label,value){const url=webUrl(value);return !url?label:!label||label.trim()===url?url:label+'（'+url+'）';}
function markdownLink(label,value){const url=webUrl(value);return !url?label:!label||label.trim()===url?url:'['+label.replace(/[\[\]\\]/g,'\\$&')+'](<'+url.replace(/>/g,'%3E')+'>)';}

// Transcript renders links directly; Markdown source is preserved by copyReply.
module.exports={markdownLink,plainLinks:text=>text};
