// Content script injected into the P.IGE page when it is opened inside Thunderbird.
// It tells the page that mail actions are available, and relays its requests to the
// extension. The page cannot reach Thunderbird's APIs on its own.

document.documentElement.dataset.pigeThunderbird = '1';
window.dispatchEvent(new Event('pige-bridge-ready'));

window.addEventListener('message', (event) => {
  if (event.source !== window || event.origin !== window.location.origin) return;
  const data = event.data;
  if (!data || data.source !== 'pige-web' || data.type !== 'open-mail') return;
  if (typeof data.messageId !== 'string' || data.messageId.length > 998) return;
  browser.runtime.sendMessage({ type: 'open-mail', messageId: data.messageId });
});
