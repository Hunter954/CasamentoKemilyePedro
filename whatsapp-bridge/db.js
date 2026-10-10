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
let inboxReady;
function ensureInbox() {
  if (!inboxReady) inboxReady = getPool().query(`CREATE TABLE IF NOT EXISTS whatsapp_contact_inbox (
    event_key TEXT PRIMARY KEY, payload JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), last_error TEXT NOT NULL DEFAULT ''
  )`).catch(error => { inboxReady = null; throw error; });
  return inboxReady;
}
async function contactSettings() {
  const result = await getPool().query("SELECT enabled, group_jid, EXTRACT(EPOCH FROM activated_at AT TIME ZONE 'UTC')::double precision AS activated_at FROM contact_import_settings WHERE id=1");
  return result.rows[0] || { enabled: false };
}
async function enqueueContact(payload) {
  await ensureInbox();
  const key = require('node:crypto').createHash('sha256').update(`${payload.groupJid}:${payload.messageId}`).digest('hex');
  await getPool().query('INSERT INTO whatsapp_contact_inbox(event_key,payload) VALUES($1,$2::jsonb) ON CONFLICT(event_key) DO NOTHING', [key, JSON.stringify(payload)]);
}
async function pendingContacts() {
  await ensureInbox();
  return (await getPool().query('SELECT event_key,payload,attempts FROM whatsapp_contact_inbox WHERE next_attempt_at <= NOW() ORDER BY created_at LIMIT 20')).rows;
}
async function finishContact(key) { await getPool().query('DELETE FROM whatsapp_contact_inbox WHERE event_key=$1', [key]); }
async function retryContact(key, attempts, error) {
  const seconds = Math.min(300, 5 * 2 ** Math.min(attempts, 6));
  await getPool().query("UPDATE whatsapp_contact_inbox SET attempts=attempts+1,last_error=$2,next_attempt_at=NOW()+($3 * INTERVAL '1 second') WHERE event_key=$1", [key, String(error).slice(0, 240), seconds]);
}
async function contactQueueStatus() {
  await ensureInbox();
  return (await getPool().query('SELECT COUNT(*)::int AS pending, COUNT(*) FILTER(WHERE attempts>0)::int AS retrying FROM whatsapp_contact_inbox')).rows[0];
}
module.exports={read,write,del,clear,updateDispatchStatus,contactSettings,enqueueContact,pendingContacts,finishContact,retryContact,contactQueueStatus};
