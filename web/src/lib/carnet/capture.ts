// Notes taken without network: kept on the device (IndexedDB) and sent when the network
// returns. Each note carries ids chosen here, and the server recognises an id it already
// has, so sending a note twice (a reply lost on the way back) never creates a duplicate.

import { ApiError } from '../api.js';
import { v2, type EntryKind, type Person, type Tree } from '../api2.js';
import { read, type KnownProject } from '../feuillet.js';

export interface Capture {
	id: string;
	text: string;
	day: string;
	start_time: string | null;
	target: { project_id?: string | null; space_id?: string | null };
	kind: EntryKind;
	title: string;
	people: string[];
	tags: string[];
	tasks: { id: string; title: string }[];
	source: 'capture' | 'journal';
	queued_at: string;
}

export interface Refused extends Capture {
	reason: string;
}

const DB_NAME = 'pige-carnet';
const DB_VERSION = 1;

function open(): Promise<IDBDatabase> {
	return new Promise((resolve, reject) => {
		const req = indexedDB.open(DB_NAME, DB_VERSION);
		req.onupgradeneeded = () => {
			const db = req.result;
			db.createObjectStore('captures', { keyPath: 'id' });
			db.createObjectStore('refused', { keyPath: 'id' });
			db.createObjectStore('cache');
		};
		req.onsuccess = () => resolve(req.result);
		req.onerror = () => reject(req.error);
	});
}

async function tx<T>(store: string, mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T> | void): Promise<T | undefined> {
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

export const captures = {
	add: (c: Capture) => tx('captures', 'readwrite', (s) => void s.put(c)),
	list: async () =>
		((await tx<Capture[]>('captures', 'readonly', (s) => s.getAll())) ?? []).sort((a, b) => a.queued_at.localeCompare(b.queued_at)),
	remove: (id: string) => tx('captures', 'readwrite', (s) => void s.delete(id))
};

export const refused = {
	add: (c: Refused) => tx('refused', 'readwrite', (s) => void s.put(c)),
	list: async () => (await tx<Refused[]>('refused', 'readonly', (s) => s.getAll())) ?? [],
	remove: (id: string) => tx('refused', 'readwrite', (s) => void s.delete(id))
};

/** What the capture screen needs to work offline: the tree, the people, « was signed in ». */
export const cache = {
	save: (tree: Tree, people: Person[]) =>
		tx('cache', 'readwrite', (s) => {
			s.put(tree, 'tree');
			s.put(people.map((p) => ({ id: p.id, display_name: p.display_name })), 'people');
			s.put(true, 'signedIn');
		}),
	tree: async () => (await tx<Tree>('cache', 'readonly', (s) => s.get('tree'))) ?? null,
	people: async () => (await tx<Person[]>('cache', 'readonly', (s) => s.get('people'))) ?? [],
	signedIn: async () => (await tx<boolean>('cache', 'readonly', (s) => s.get('signedIn'))) === true,
	forget: () =>
		tx('cache', 'readwrite', (s) => {
			s.delete('tree');
			s.delete('people');
			s.put(false, 'signedIn');
		})
};

export function newId(): string {
	if (typeof crypto.randomUUID === 'function') return crypto.randomUUID().replace(/-/g, '');
	const bytes = crypto.getRandomValues(new Uint8Array(16));
	return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

function localNow(): { day: string; time: string } {
	const now = new Date();
	const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString();
	return { day: local.slice(0, 10), time: local.slice(11, 16) };
}

/**
 * A note ready to send: filed the same way as a journal paragraph (project named in the
 * text, @people, #tags, [ ] tasks, « Décision : »). ``place`` forces where it goes.
 */
export function prepare(
	text: string,
	tree: Tree | null,
	people: Pick<Person, 'display_name'>[],
	options: { place?: Capture['target'] | null; fallbackSpace?: string | null; day?: string; source?: Capture['source'] } = {}
): Capture {
	const projects: KnownProject[] = tree?.spaces.flatMap((s) => s.projects) ?? [];
	const reading = read(text, projects, people);
	const now = localNow();
	const day = options.day ?? now.day;
	const target =
		options.place ??
		(reading.project ? { project_id: reading.project.id } : { space_id: options.fallbackSpace ?? tree?.spaces[0]?.id ?? null });
	return {
		id: newId(),
		text,
		day,
		start_time: day === now.day ? now.time : null,
		target,
		kind: reading.kind,
		title: reading.title,
		people: reading.people,
		tags: reading.tags,
		tasks: reading.tasks.map((title) => ({ id: newId(), title })),
		source: options.source ?? 'capture',
		queued_at: new Date().toISOString()
	};
}

export type SendResult = 'ok' | 'offline' | 'unauthenticated' | 'refused';

/** Stop reason when the whole queue must wait, or null when only this note is rejected. */
function classify(err: unknown): SendResult | null {
	if (!(err instanceof ApiError)) return 'offline';
	if (err.status === 0 || err.status >= 500 || err.status === 429) return 'offline';
	if (err.status === 401) return 'unauthenticated';
	if (err.status === 403) return 'refused';
	return null;
}

/** Send one note and its tasks. Safe to repeat: the ids make every call idempotent. */
export async function send(c: Capture): Promise<void> {
	const where = { project_id: c.target.project_id ?? null, space_id: c.target.project_id ? null : (c.target.space_id ?? null) };
	await v2.createEntry({
		id: c.id,
		entry_date: c.day,
		...where,
		kind: c.kind,
		title: c.title,
		body: c.text,
		start_time: c.start_time,
		source: c.source,
		people: c.people,
		tags: c.tags
	});
	for (const task of c.tasks) {
		await v2.createTask({ id: task.id, title: task.title, ...where, origin_entry_id: c.id });
	}
}

let running: Promise<SendResult> | null = null;

/** Send the queue, oldest first. Notes the server refuses go to « refused », never lost. */
export function flush(): Promise<SendResult> {
	running ??= (async () => {
		try {
			for (const c of await captures.list()) {
				try {
					await send(c);
					await captures.remove(c.id);
				} catch (err) {
					const stop = classify(err);
					if (stop) return stop;
					await refused.add({ ...c, reason: err instanceof Error ? err.message : String(err) });
					await captures.remove(c.id);
				}
			}
			return 'ok' as const;
		} finally {
			running = null;
		}
	})();
	return running;
}
