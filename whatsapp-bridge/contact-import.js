const db = require('./db');
const { contactBatches } = require('./contact-cards');
let draining = false;
async function receiveContacts(event, normalizeMessageContent) {
  const batches = contactBatches(event, normalizeMessageContent);
  if (!batches.length) return;
  const settings = await db.contactSettings();
  if (!settings.enabled || !settings.group_jid || !settings.activated_at) return;
  for (const batch of batches) {
    if (batch.groupJid === settings.group_jid && batch.timestamp >= Math.floor(settings.activated_at)) await db.enqueueContact(batch);
  }
  await drainContacts();
}
async function drainContacts() {
  if (draining || !process.env.WA_INTERNAL_TOKEN) return;
  draining = true;
  try {
    for (const item of await db.pendingContacts()) {
      try {
        const response = await fetch(`http://127.0.0.1:${process.env.PORT || 8000}/api/whatsapp/contacts/import`, {
          method: 'POST', headers: { 'Content-Type': 'application/json', 'X-WA-Internal-Token': process.env.WA_INTERNAL_TOKEN },
          body: JSON.stringify(item.payload), signal: AbortSignal.timeout(15000)
        });
        if (!response.ok) throw new Error(`Importação respondeu HTTP ${response.status}`);
        const result = await response.json();
        if (!result.ok) throw new Error('Importação sem confirmação');
        await db.finishContact(item.event_key);
      } catch (error) {
        await db.retryContact(item.event_key, item.attempts, error.message);
        console.warn('Importação de contatos será tentada novamente:', error.message);
      }
    }
  } finally { draining = false; }
}
function startContactWorker() {
  const tick = () => drainContacts().catch(error => console.warn('Fila de contatos:', error.message));
  const timer = setInterval(tick, 10000);
  timer.unref();
  tick();
}
module.exports = { receiveContacts, drainContacts, startContactWorker };
