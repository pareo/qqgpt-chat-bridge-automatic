'use strict';
const fs=require('node:fs'),path=require('node:path');
function safeArtifact(root,file,limit){
 const base=fs.realpathSync(root),real=fs.realpathSync(file),relative=path.relative(base,real),stat=fs.statSync(real);
 if(!relative||relative.startsWith('..')||path.isAbsolute(relative)||!stat.isFile()||stat.size<1||stat.size>limit)throw Error('Artifact outside task storage or size limit');
 return real;
}
module.exports={safeArtifact};
