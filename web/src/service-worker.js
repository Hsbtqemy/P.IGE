// Offline shell for the P.IGE web app.
// - The app shell (HTML, JS, CSS, fonts, icons) is cached at install, so the app opens without network.
// - API calls are never cached here: the app keeps its own snapshot and outbox in IndexedDB.

import { self } from '$app/service-worker';
import { immutable, assets, prerendered } from '$app/manifest';
import { version } from '$app/env';

const CACHE = `pige-shell-${version}`;
// Paths are relative to the app root; resolve them against the scope, not the worker URL
// (an empty path, the prerendered home page, would otherwise resolve to this script).
const ROOT = new URL('./', self.registration.scope).href;
const SHELL = [...immutable, ...assets, ...prerendered].map((f) => new URL(f.path || './', ROOT).href);
// Shell of the interface pages (/journal/…), served by the server for unknown paths.
const APP_SHELL = new URL('200.html', ROOT).href;

self.addEventListener('install', (/** @type {Event & {waitUntil(p: Promise<unknown>): void}} */ event) => {
	event.waitUntil(
		caches
			.open(CACHE)
			.then((cache) => cache.addAll([...SHELL, APP_SHELL]))
			.then(() => self.skipWaiting())
	);
});

self.addEventListener('activate', (/** @type {Event & {waitUntil(p: Promise<unknown>): void}} */ event) => {
	event.waitUntil(
		caches
			.keys()
			.then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
			.then(() => self.clients.claim())
	);
});

self.addEventListener('fetch', (/** @type {Event & {request: Request, respondWith(r: Promise<Response> | Response): void}} */ event) => {
	const request = event.request;
	if (request.method !== 'GET') return;
	const url = new URL(request.url);
	if (url.origin !== self.location.origin || url.pathname.startsWith('/api/')) return;

	if (request.mode === 'navigate') {
		// Network first so a new version shows up at once; cached shell when offline.
		event.respondWith(
			fetch(request).catch(async () => {
				const isHome = url.href === ROOT || url.pathname === '/index.html';
				return (await caches.match(isHome ? ROOT : APP_SHELL)) ?? (await caches.match(ROOT)) ?? Response.error();
			})
		);
		return;
	}
	event.respondWith(caches.match(request).then((cached) => cached ?? fetch(request)));
});
