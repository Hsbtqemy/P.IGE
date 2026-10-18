// When the interface is open inside Thunderbird (P.IGE space), the extension's bridge
// (thunderbird/bridge.js) lets the page reopen the email behind an entry, and asks the
// page to refresh after a mail was filed from the message list.

export const thunderbird = $state({ available: false });

function detect() {
	thunderbird.available = document.documentElement.dataset.pigeThunderbird === '1';
}

if (typeof window !== 'undefined') {
	detect();
	window.addEventListener('pige-bridge-ready', detect);
}

/** Reopen an email in Thunderbird, by its Message-ID header. */
export function openMail(messageId: string) {
	window.postMessage({ source: 'pige-web', type: 'open-mail', messageId }, window.location.origin);
}

/** Run ``refresh`` when a mail was filed from Thunderbird; returns the cleanup. */
export function onMailFiled(refresh: () => void): () => void {
	window.addEventListener('pige-refresh', refresh);
	return () => window.removeEventListener('pige-refresh', refresh);
}
