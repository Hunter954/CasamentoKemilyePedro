let running = false;
async function tickCampaigns() {
  if (running || !process.env.WA_INTERNAL_TOKEN) return;
  running = true;
  try {
    const response = await fetch(`http://127.0.0.1:${process.env.PORT || 8000}/api/whatsapp/campaigns/tick`, {
      method: 'POST', headers: {'X-WA-Internal-Token': process.env.WA_INTERNAL_TOKEN},
      signal: AbortSignal.timeout(60000)
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
  } finally { running = false; }
}
function startCampaignWorker() {
  const timer = setInterval(() => tickCampaigns().catch(error => console.warn('[Campaign queue]', error.message)), 2000);
  timer.unref();
}
module.exports = {startCampaignWorker, tickCampaigns};
