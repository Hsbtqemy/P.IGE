// The queue of notes waiting for the network, shown wherever it matters, sent on its own.

import { captures, flush, refused, type Capture, type Refused, type SendResult } from './capture.js';

export const outbox = $state<{ pending: Capture[]; refused: Refused[]; last: SendResult | ''; syncing: boolean }>({
	pending: [],
	refused: [],
	last: '',
	syncing: false
});

export async function refreshOutbox(): Promise<void> {
	try {
		const [p, r] = await Promise.all([captures.list(), refused.list()]);
		outbox.pending = p;
		outbox.refused = r;
	} catch {
		/* IndexedDB unavailable (private browsing): nothing queued here */
	}
}

export async function sync(): Promise<SendResult | ''> {
	await refreshOutbox();
	if (!outbox.pending.length) return outbox.last;
	outbox.syncing = true;
	try {
		outbox.last = await flush();
	} catch {
		outbox.last = 'offline';
	} finally {
		outbox.syncing = false;
		await refreshOutbox();
	}
	return outbox.last;
}

/** Send now, when the network comes back, and every 30 s while the page is open. */
export function autoSync(): () => void {
	const run = () => void sync();
	window.addEventListener('online', run);
	const visible = () => document.visibilityState === 'visible' && run();
	document.addEventListener('visibilitychange', visible);
	const timer = setInterval(run, 30_000);
	run();
	return () => {
		window.removeEventListener('online', run);
		document.removeEventListener('visibilitychange', visible);
		clearInterval(timer);
	};
}

export async function queue(c: Capture): Promise<void> {
	await captures.add(c);
	await refreshOutbox();
}

export async function dropRefused(id: string): Promise<void> {
	await refused.remove(id);
	await refreshOutbox();
}

/** A refused note goes back in the queue (after the cause was fixed, e.g. a project restored). */
export async function retryRefused(r: Refused): Promise<void> {
	const { reason: _reason, ...c } = r;
	await captures.add(c);
	await refused.remove(r.id);
	await sync();
}
