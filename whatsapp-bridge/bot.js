const { Boom } = require('@hapi/boom');
const qrcode = require('qrcode');
const db = require('./db');
let sock=null, starting=false, reconnectTimer=null;
const sessionId=process.env.WA_SESSION_ID || 'kemily-pedro-casamento';
const state={ready:false,qr:null,status:'Aguardando início',lastError:null,connectedAt:null,lastQrAt:null,phone:null};
function normalizePhone(v){const d=String(v||'').replace(/\D/g,''); if(!d)return ''; return (d.length===10||d.length===11)?`55${d}`:d;}
function jid(v){const p=normalizePhone(v); return p?`${p}@s.whatsapp.net`:'';}
async function authState(baileys){
  const {initAuthCreds,BufferJSON,proto}=baileys;
  const ser=x=>JSON.parse(JSON.stringify(x,BufferJSON.replacer));
  const de=x=>x?JSON.parse(JSON.stringify(x),BufferJSON.reviver):null;
  const read=k=>db.read(sessionId,k).then(de), write=(k,v)=>db.write(sessionId,k,ser(v)), del=k=>db.del(sessionId,k);
  const creds=(await read('creds'))||initAuthCreds();
  return {state:{creds,keys:{get:async(type,ids)=>{const out={}; await Promise.all(ids.map(async id=>{let v=await read(`${type}-${id}`); if(type==='app-state-sync-key'&&v&&proto?.Message?.AppStateSyncKeyData)v=proto.Message.AppStateSyncKeyData.fromObject(v); out[id]=v;})); return out;},set:async data=>{const jobs=[]; for(const type of Object.keys(data||{})) for(const id of Object.keys(data[type]||{})){const v=data[type][id],k=`${type}-${id}`; jobs.push(v?write(k,v):del(k));} await Promise.all(jobs);}}},saveCreds:()=>write('creds',creds)};
}
async function stop(logout=false){
  if(reconnectTimer){clearTimeout(reconnectTimer); reconnectTimer=null;}
  try{ if(sock){sock.ev.removeAllListeners(); if(logout) await sock.logout(); else sock.ws?.close?.();} }catch(e){}
  sock=null; state.ready=false; state.qr=null; state.status='WhatsApp parado';
}
async function start(clean=false){
  if(starting||sock) return; starting=true; state.status='Iniciando WhatsApp'; state.lastError=null;
  try{
    if(clean) await db.clear(sessionId);
    const baileys=require('@whiskeysockets/baileys');
    const {default:makeWASocket,DisconnectReason,fetchLatestBaileysVersion}=baileys;
    const auth=await authState(baileys); const ver=await fetchLatestBaileysVersion().catch(()=>({version:undefined}));
    sock=makeWASocket({version:ver.version,auth:auth.state,printQRInTerminal:false,browser:['Kemily & Pedro','Chrome','2.0.0'],syncFullHistory:false,markOnlineOnConnect:false,generateHighQualityLinkPreview:false,defaultQueryTimeoutMs:120000,connectTimeoutMs:120000});
    sock.ev.on('creds.update',auth.saveCreds);
    sock.ev.on('messages.update', async updates => {
      for (const item of updates || []) {
        const id = item?.key?.id;
        const code = Number(item?.update?.status || 0);
        const status = code >= 5 ? 'read' : code >= 4 ? 'delivered' : code >= 2 ? 'sent' : null;
        if (id && status) await db.updateDispatchStatus(id, status);
      }
    });

    sock.ev.on('connection.update',async u=>{
      if(u.qr){state.qr=await qrcode.toDataURL(u.qr,{margin:1,scale:8}); state.lastQrAt=new Date().toISOString(); state.status='Aguardando leitura do QR Code'; state.ready=false;}
      if(u.connection==='connecting') state.status=state.qr?'Aguardando leitura do QR Code':'Conectando ao WhatsApp';
      if(u.connection==='open'){state.ready=true; state.qr=null; state.status='Conectado via Baileys'; state.connectedAt=new Date().toISOString(); state.lastError=null; state.phone=String(sock.user?.id||'').split(':')[0].split('@')[0]||null;}
      if(u.connection==='close'){
        state.ready=false; const reason=u.lastDisconnect?.error?new Boom(u.lastDisconnect.error)?.output?.statusCode:undefined; const reconnect=reason!==DisconnectReason.loggedOut;
        state.lastError=u.lastDisconnect?.error?.message||null; state.status=reconnect?'Conexão caiu, reconectando':'WhatsApp desconectado'; sock=null;
        if(reconnect){reconnectTimer=setTimeout(()=>start(false).catch(()=>{}),5000);}
      }
    });
  }catch(e){sock=null; state.ready=false; state.status='Erro ao iniciar WhatsApp'; state.lastError=e.message; throw e;} finally{starting=false;}
}
async function sendText(phone,text){if(!sock||!state.ready) throw new Error('WhatsApp não está conectado. Abra Conexão WhatsApp e leia o QR Code.'); const r=await sock.sendMessage(jid(phone),{text:String(text||'')}); return {id:r?.key?.id||'',remoteJid:r?.key?.remoteJid||''};}
async function sendImage(phone,url,caption=''){if(!sock||!state.ready) throw new Error('WhatsApp não está conectado. Abra Conexão WhatsApp e leia o QR Code.'); const r=await sock.sendMessage(jid(phone),{image:{url:String(url)},caption:String(caption||'')}); return {id:r?.key?.id||'',remoteJid:r?.key?.remoteJid||''};}
function getState(){return {...state,starting,engine:'baileys',authStore:'PostgreSQL',sessionId};}
module.exports={start,stop,sendText,sendImage,getState,clear:()=>db.clear(sessionId)};
