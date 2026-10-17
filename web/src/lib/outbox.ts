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
const DB_VERSION = 1;

function open(): Promise<IDBDatabase> {
	return new Promise((resolve, reject) => {
		const req = indexedDB.open(DB_NAME, DB_VERSION);
		req.onupgradeneeded = () => {
			const db = req.result;
			db.createObjectStore('outbox', { keyPath: 'id' });
			db.createObjectStore('changes', { keyPath: 'id' });
			db.createObjectStore('snapshot');
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
		t.onerror = () => {
			db.close();
			reject(t.error);
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

export const snapshot = {
	save: (tasks: Task[]) => tx('snapshot', 'readwrite', (s) => void s.put(tasks, 'tasks')),
	load: async () => ((await tx<Task[]>('snapshot', 'readonly', (s) => s.get('tasks'))) ?? null)
};

export type FlushResult = 'ok' | 'offline' | 'unauthenticated';

/**
 * Send queued captures and status changes, oldest first. Stops at the first
 * network failure or expired session; drops items the server rejects as invalid
 * so a bad item never blocks the queue.
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

/** Returns a stop reason for transient failures, or null when the item should be dropped. */
function classify(err: unknown): FlushResult | null {
	if (!(err instanceof ApiError)) return 'offline';
	if (err.status === 0 || err.status >= 500 || err.status === 429) return 'offline';
	if (err.status === 401 || err.status === 403) return 'unauthenticated';
	return null;
}
