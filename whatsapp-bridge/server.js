const http=require('http'); const bot=require('./bot');
const db=require('./db'); const {startContactWorker}=require('./contact-import');
const PORT=Number(process.env.WA_BRIDGE_PORT||3100); const HOST='127.0.0.1';
function json(res,code,data){res.writeHead(code,{'Content-Type':'application/json; charset=utf-8'});res.end(JSON.stringify(data));}
function body(req){return new Promise((resolve,reject)=>{let s='';req.on('data',c=>{s+=c;if(s.length>5e6)req.destroy();});req.on('end',()=>{try{resolve(s?JSON.parse(s):{})}catch(e){reject(e)}});req.on('error',reject);});}
const server=http.createServer(async(req,res)=>{try{
  if(req.method==='GET'&&req.url==='/health') return json(res,200,{ok:true,...bot.getState()});
  if(req.method==='GET'&&req.url==='/status') return json(res,200,bot.getState());
  if(req.method==='GET'&&req.url==='/groups') return json(res,200,{groups:await bot.listGroups()});
  if(req.method==='GET'&&req.url==='/contacts/status') return json(res,200,{ready:bot.getState().ready,...await db.contactQueueStatus()});
  if(req.method==='POST'&&req.url==='/start'){const b=await body(req); await bot.start(Boolean(b.clean)); return json(res,200,{ok:true,...bot.getState()});}
  if(req.method==='POST'&&req.url==='/disconnect'){await bot.stop(false); return json(res,200,{ok:true,...bot.getState()});}
  if(req.method==='POST'&&req.url==='/reset'){await bot.stop(true); await bot.clear(); await bot.start(false); return json(res,200,{ok:true,...bot.getState()});}
  if(req.method==='POST'&&req.url==='/send-text'){const b=await body(req); const r=await bot.sendText(b.phone,b.message); return json(res,200,{ok:true,messageId:r.id,result:r});}
  if(req.method==='POST'&&req.url==='/send-image'){const b=await body(req); const r=await bot.sendImage(b.phone,b.image,b.caption); return json(res,200,{ok:true,messageId:r.id,result:r});}
  return json(res,404,{ok:false,error:'not found'});
}catch(e){return json(res,500,{ok:false,error:e.message});}});
server.listen(PORT,HOST,()=>{console.log(`[WhatsApp bridge] ${HOST}:${PORT}`); startContactWorker(); require('./campaign-worker').startCampaignWorker(); if(String(process.env.WA_DISABLE_AUTO_START||'false')!=='true') setTimeout(()=>bot.start(false).catch(e=>console.error('[WhatsApp]',e.message)),2500);});
