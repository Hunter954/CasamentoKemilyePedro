// Shared contact cards only: never import the address book or plain chat text.
function unescapeVcard(value) {
  return String(value || '').replace(/\\[nN]/g, ' ').replace(/\\([,;\\])/g, '$1').trim();
}
function parseCard(card) {
  const lines = String(card?.vcard || '').replace(/\r\n/g, '\n').replace(/\n[ \t]/g, '').split('\n');
  let name = '', structuredName = '', fallback = '', cell = '', waid = '';
  for (const line of lines) {
    const colon = line.indexOf(':');
    if (colon < 0) continue;
    const field = line.slice(0, colon), value = line.slice(colon + 1);
    const property = field.split(';')[0].split('.').pop().toUpperCase();
    if (property === 'FN') name = unescapeVcard(value);
    if (property === 'N') structuredName = value.split(';').slice(0, 2).reverse().map(unescapeVcard).filter(Boolean).join(' ');
    if (property === 'TEL') {
      const id = field.match(/(?:^|;)waid=(\d+)/i)?.[1];
      if (id && !waid) waid = '+' + id;
      const number = value.replace(/^tel:/i, '').trim();
      if (number && !fallback) fallback = number;
      if (/(?:^|[;,=])CELL(?:[;,]|$)/i.test(field) && !cell) cell = number;
    }
  }
  return { name: (name || unescapeVcard(card?.displayName) || structuredName).slice(0, 180), phone: (waid || cell || fallback).slice(0, 40) };
}
function contactBatches(event, normalizeMessageContent = value => value) {
  // 'append' includes offline delivery. Flask checks the activation date too.
  if (!['notify', 'append'].includes(event?.type)) return [];
  const batches = [];
  for (const message of event.messages || []) {
    const group = message?.key?.remoteJid;
    if (!group?.endsWith('@g.us') || !message?.key?.id || !message.message) continue;
    const content = normalizeMessageContent(message.message);
    const cards = content?.contactMessage ? [content.contactMessage] : content?.contactsArrayMessage?.contacts;
    if (!Array.isArray(cards) || !cards.length) continue;
    const timestamp = Number(message.messageTimestamp);
    if (!Number.isFinite(timestamp) || timestamp <= 0) continue;
    for (let i = 0; i < cards.length; i += 100) {
      batches.push({ groupJid: group, messageId: `${message.key.id}:${i / 100}`, timestamp,
        senderName: String(message.pushName || (message.key.fromMe ? 'WhatsApp dos noivos' : 'Participante do grupo')).slice(0, 180), contacts: cards.slice(i, i + 100).map(parseCard) });
    }
  }
  return batches;
}
module.exports = { parseCard, contactBatches };
