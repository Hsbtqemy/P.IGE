// Offline storage in IndexedDB:
//  - "outbox": captures not yet acknowledged by the server, sent when the network returns;
//  - "snapshot": the last task list received, shown when offline.
// Each capture carries an id created on the device, and the server treats a repeated
// id as the same task, so sending twice never creates a duplicate.

import { api, ApiError, type NewTask, type Task } from './api.js';

export interface Pending extends NewTask {
	queued_at: string;
}

type Change = 'done';
export interface PendingChange {
	id: string;
	change: Change;
	queued_at: string;
}

const DB_NAME = 'pige';
const DB_VERSION = 2;

function open(): Promise<IDBDatabase> {
	return new Promise((resolve, reject) => {
		const req = indexedDB.open(DB_NAME, DB_VERSION);
		req.onupgradeneeded = (event) => {
			const db = req.result;
			if (event.oldVersion < 1) {
				db.createObjectStore('outbox', { keyPath: 'id' });
				db.createObjectStore('changes', { keyPath: 'id' });
				db.createObjectStore('snapshot');
			}
			if (event.oldVersion < 2) {
				// Captures the server refused: kept and shown, never silently dropped.
				db.createObjectStore('failed', { keyPath: 'id' });
			}
		};
		req.onsuccess = () => resolve(req.result);
		req.onerror = () => reject(req.error);
	});
}

async function tx<T>(
	store: string,
	mode: IDBTransactionMode,
	fn: (s: IDBObjectStore) => IDBRequest<T> | void
): Promise<T | undefined> {
	const db = await open();
	return new Promise((resolve, reject) => {
		const t = db.transaction(store, mode);
		const req = fn(t.objectStore(store));
		t.oncomplete = () => {
			db.close();
			resolve(req ? req.result : undefined);
		};
		t.onerror = t.onabort = () => {
			db.close();
			reject(t.error ?? new Error('IndexedDB transaction aborted'));
		};
	});
}

export const outbox = {
	add: (item: Pending) => tx('outbox', 'readwrite', (s) => void s.put(item)),
	list: async () => ((await tx<Pending[]>('outbox', 'readonly', (s) => s.getAll())) ?? []),
	remove: (id: string) => tx('outbox', 'readwrite', (s) => void s.delete(id))
};

export const changes = {
	add: (item: PendingChange) => tx('changes', 'readwrite', (s) => void s.put(item)),
	list: async () => ((await tx<PendingChange[]>('changes', 'readonly', (s) => s.getAll())) ?? []),
	remove: (id: string) => tx('changes', 'readwrite', (s) => void s.delete(id))
};

export interface Failed extends Pending {
	reason: string;
}

export const failed = {
	add: (item: Failed) => tx('failed', 'readwrite', (s) => void s.put(item)),
	list: async () => ((await tx<Failed[]>('failed', 'readonly', (s) => s.getAll())) ?? []),
	remove: (id: string) => tx('failed', 'readwrite', (s) => void s.delete(id))
};

export const snapshot = {
	save: (tasks: Task[]) => tx('snapshot', 'readwrite', (s) => void s.put(tasks, 'tasks')),
	load: async () => ((await tx<Task[]>('snapshot', 'readonly', (s) => s.get('tasks'))) ?? null),
	/** Remembered so the app can open offline only for someone who was signed in. */
	setSignedIn: (value: boolean) => tx('snapshot', 'readwrite', (s) => void s.put(value, 'signedIn')),
	signedIn: async () => (await tx<boolean>('snapshot', 'readonly', (s) => s.get('signedIn'))) === true,
	/** On logout: forget task titles kept on this device (unsent captures stay queued). */
	clear: () =>
		tx('snapshot', 'readwrite', (s) => {
			s.delete('tasks');
			s.put(false, 'signedIn');
		})
};

export type FlushResult = 'ok' | 'offline' | 'unauthenticated' | 'refused';

/**
 * Send queued captures and status changes, oldest first. Stops at the first
 * network failure or expired session. A capture the server rejects as invalid
 * moves to the "failed" store, so it never blocks the queue and is never lost.
 */
export async function flush(): Promise<FlushResult> {
	const pending = (await outbox.list()).sort((a, b) => a.queued_at.localeCompare(b.queued_at));
	for (const item of pending) {
		const { queued_at: _queued, ...task } = item;
		try {
			await api.createTask(task);
			await outbox.remove(item.id);
		} catch (err) {
			const result = classify(err);
			if (result) return result;
			await failed.add({ ...item, reason: err instanceof Error ? err.message : String(err) });
			await outbox.remove(item.id);
		}
	}
	for (const item of await changes.list()) {
		try {
			await api.setStatus(item.id, 'done');
			await changes.remove(item.id);
		} catch (err) {
			const result = classify(err);
			if (result) return result;
			await changes.remove(item.id);
		}
	}
	return 'ok';
}

/**
 * Returns a stop reason when the whole queue must wait (network, expired session,
 * server refusing every write), or null when only this item is rejected.
 */
function classify(err: unknown): FlushResult | null {
	if (!(err instanceof ApiError)) return 'offline';
	if (err.status === 0 || err.status >= 500 || err.status === 429) return 'offline';
	if (err.status === 401) return 'unauthenticated';
	if (err.status === 403) return 'refused';
	return null;
}
