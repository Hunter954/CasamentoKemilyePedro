const { Pool } = require('pg');
let pool;
function connectionString(){ return process.env.DATABASE_URL || process.env.POSTGRES_URL || ''; }
function getPool(){
  if (pool) return pool;
  const cs = connectionString();
  if (!cs) throw new Error('DATABASE_URL não configurada para persistir a sessão do WhatsApp.');
  pool = new Pool({ connectionString: cs, ssl: /sslmode=(require|no-verify)/i.test(cs) ? {rejectUnauthorized:false} : false, max: 5 });
  return pool;
}
async function ensureTable(){
  await getPool().query(`CREATE TABLE IF NOT EXISTS whatsapp_auth (
    session_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value JSONB,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY(session_id,key)
  )`);
}
async function read(sessionId,key){ await ensureTable(); const r=await getPool().query('SELECT value FROM whatsapp_auth WHERE session_id=$1 AND key=$2',[sessionId,key]); return r.rows[0]?.value || null; }
async function write(sessionId,key,value){ await ensureTable(); await getPool().query(`INSERT INTO whatsapp_auth(session_id,key,value,updated_at) VALUES($1,$2,$3,NOW()) ON CONFLICT(session_id,key) DO UPDATE SET value=EXCLUDED.value,updated_at=NOW()`,[sessionId,key,value]); }
async function del(sessionId,key){ await ensureTable(); await getPool().query('DELETE FROM whatsapp_auth WHERE session_id=$1 AND key=$2',[sessionId,key]); }
async function clear(sessionId){ await ensureTable(); await getPool().query('DELETE FROM whatsapp_auth WHERE session_id=$1',[sessionId]); }
async function updateDispatchStatus(messageId,status){
  if(!messageId) return;
  try{
    await getPool().query(`UPDATE whatsapp_dispatch SET status=$2, updated_at=NOW() WHERE provider_message_id=$1`,[String(messageId),String(status)]);
  }catch(error){ console.warn('[WhatsApp] Não foi possível atualizar status do disparo:', error.message); }
}
module.exports={read,write,del,clear,updateDispatchStatus};
