const test = require('node:test');
const assert = require('node:assert/strict');
const {tickCampaigns} = require('../whatsapp-bridge/campaign-worker');

test('campaign worker requires a token and prevents overlapping ticks', async () => {
  const originalFetch = global.fetch;
  const originalToken = process.env.WA_INTERNAL_TOKEN;
  let calls = 0, release;
  global.fetch = async (url, options) => {
    calls++;
    assert.ok(url.endsWith('/api/whatsapp/campaigns/tick'));
    assert.equal(options.headers['X-WA-Internal-Token'], 'test-only');
    await new Promise(resolve => { release = resolve; });
    return {ok:true};
  };
  try {
    delete process.env.WA_INTERNAL_TOKEN;
    await tickCampaigns();
    assert.equal(calls, 0);
    process.env.WA_INTERNAL_TOKEN = 'test-only';
    const first = tickCampaigns();
    await tickCampaigns();
    assert.equal(calls, 1);
    release();
    await first;
    global.fetch = async () => ({ok:false,status:503});
    await assert.rejects(tickCampaigns(), /HTTP 503/);
    global.fetch = async () => ({ok:true});
    await tickCampaigns(); // failed ticks release the in-process guard
  } finally {
    global.fetch = originalFetch;
    if (originalToken === undefined) delete process.env.WA_INTERNAL_TOKEN;
    else process.env.WA_INTERNAL_TOKEN = originalToken;
  }
});
