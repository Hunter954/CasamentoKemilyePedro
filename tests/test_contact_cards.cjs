const { test, beforeEach } = require('node:test');
const assert = require('node:assert/strict');
const { parseCard, contactBatches } = require('../whatsapp-bridge/contact-cards');
const card = { displayName: 'Ana', vcard: 'BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Ana Silva\r\nTEL;type=CELL;waid=5545999991234:+55 (45) 99999-1234\r\nEND:VCARD' };
const message = (content, key = {}) => ({ key: { id: 'message-1', remoteJid: '123@g.us', ...key },
  messageTimestamp: 1760000000, pushName: 'Kemily', message: content });

test('vCard prefers WhatsApp number, unwraps folded names and escaped punctuation', () => {
  assert.deepEqual(parseCard(card), { name: 'Ana Silva', phone: '+5545999991234' });
  assert.deepEqual(parseCard({ vcard: 'FN:Ana\\, Maria \r\n Silva\r\nTEL;TYPE=HOME:4533331234\r\nitem1.TEL;TYPE=CELL:45999991234' }),
    { name: 'Ana, Maria Silva', phone: '45999991234' });
});
test('structured name, displayName and missing phone are handled', () => {
  assert.deepEqual(parseCard({ vcard: 'N:Silva;Ana;;;\nTEL:tel:+12025550123' }), { name: 'Ana Silva', phone: '+12025550123' });
  assert.deepEqual(parseCard({ displayName: 'Sem telefone' }), { name: 'Sem telefone', phone: '' });
});
test('single and multiple shared cards, including messages from linked account', () => {
  const batches = contactBatches({ type: 'notify', messages: [message({ contactMessage: card }, { fromMe: true }),
    message({ contactsArrayMessage: { contacts: [card, { displayName: 'Inválido' }] } }, { id: 'message-2' })] });
  assert.equal(batches.length, 2);
  assert.equal(batches[0].messageId, 'message-1:0');
  assert.equal(batches[1].contacts.length, 2);
});
test('only contact cards in groups, with date and ID, are accepted', () => {
  assert.deepEqual(contactBatches({ type: 'notify', messages: [message({ conversation: 'Ana 45999991234' }),
    message({ contactMessage: card }, { remoteJid: '5545999991234@s.whatsapp.net' }),
    message({ contactMessage: card }, { id: '' }), { ...message({ contactMessage: card }), messageTimestamp: undefined }] }), []);
  assert.deepEqual(contactBatches({ type: 'history', messages: [message({ contactMessage: card })] }), []);
});
test('offline and wrapped messages normalize; large cards batches keep stable IDs', () => {
  const batches = contactBatches({ type: 'append', messages: [message({ ephemeralMessage: { message: { contactMessage: card } } })] },
    value => value.ephemeralMessage?.message || value);
  assert.equal(batches.length, 1);
  const large = contactBatches({ type: 'notify', messages: [message({ contactsArrayMessage: { contacts: Array(201).fill(card) } })] });
  assert.deepEqual(large.map(item => item.contacts.length), [100, 100, 1]);
  assert.deepEqual(large.map(item => item.messageId), ['message-1:0', 'message-1:1', 'message-1:2']);
});

// Isolate the persistent store and transport to exercise failure/restart paths
// without touching the real WhatsApp session or sending messages.
const pending = new Map();
let config, retries, finishes;
const stubDb = {
  contactSettings: async () => config,
  enqueueContact: async payload => { const key = payload.messageId; if (!pending.has(key)) pending.set(key, { event_key: key, payload, attempts: 0 }); },
  pendingContacts: async () => [...pending.values()],
  finishContact: async key => { finishes++; pending.delete(key); },
  retryContact: async key => { retries++; pending.get(key).attempts++; }
};
const dbPath = require.resolve('../whatsapp-bridge/db');
require.cache[dbPath] = { id: dbPath, filename: dbPath, loaded: true, exports: stubDb };
const workerPath = require.resolve('../whatsapp-bridge/contact-import');
function worker() { delete require.cache[workerPath]; return require(workerPath); }
beforeEach(() => {
  pending.clear(); retries = 0; finishes = 0;
  config = { enabled: true, group_jid: '123@g.us', activated_at: 1759999900 };
  process.env.WA_INTERNAL_TOKEN = 'test-only';
  global.fetch = async () => ({ ok: true, json: async () => ({ ok: true }) });
});
test('worker filters wrong groups, old cards, and paused configuration', async () => {
  const importer = worker();
  await importer.receiveContacts({ type: 'notify', messages: [message({ contactMessage: card }, { remoteJid: 'other@g.us' }),
    { ...message({ contactMessage: card }), messageTimestamp: 1700000000 }] });
  config.enabled = false;
  await importer.receiveContacts({ type: 'notify', messages: [message({ contactMessage: card })] });
  assert.equal(pending.size, 0);
  assert.equal(finishes, 0);
});
test('temporary HTTP failure keeps batch, new worker retries and acknowledges it', async () => {
  global.fetch = async () => ({ ok: false, status: 503 });
  await worker().receiveContacts({ type: 'notify', messages: [message({ contactMessage: card })] });
  assert.equal(pending.size, 1);
  assert.equal(retries, 1);
  global.fetch = async (_url, options) => {
    assert.equal(options.headers['X-WA-Internal-Token'], 'test-only');
    assert.equal(JSON.parse(options.body).contacts[0].phone, '+5545999991234');
    return { ok: true, json: async () => ({ ok: true }) };
  };
  await worker().drainContacts();
  assert.equal(pending.size, 0);
  assert.equal(finishes, 1);
});
test('non-JSON or unacknowledged success is retained, empty token never drains', async () => {
  global.fetch = async () => ({ ok: true, json: async () => ({}) });
  const importer = worker();
  await importer.receiveContacts({ type: 'notify', messages: [message({ contactMessage: card })] });
  assert.equal(pending.size, 1);
  process.env.WA_INTERNAL_TOKEN = '';
  await importer.drainContacts();
  assert.equal(pending.size, 1);
});
