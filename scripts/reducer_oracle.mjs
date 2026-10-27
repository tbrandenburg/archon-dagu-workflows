// Test-only bulk runner: exact upstream reducer body; only its io import is replaced.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {stripTypeScriptTypes} from 'node:module';
const base=path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const original=fs.readFileSync(path.join(base,'vendor/archon/.archon/workflows/sdlc/deliver/scripts/round.ts'),'utf8');
const body=stripTypeScriptTypes(original.replace(/^import .*;$/m,''));
const execute=new Function('process','emit','text','nullableJson','artifactsDir',body);
const rows=JSON.parse(fs.readFileSync(0,'utf8'));
const results=rows.map(env=>{let result;execute({env},x=>result=x,v=>v??'',v=>!v||!v.trim()?null:JSON.parse(v),()=>'/oracle');return result;});
console.log(JSON.stringify(results));
