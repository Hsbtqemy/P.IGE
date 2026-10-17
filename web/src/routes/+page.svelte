<script lang="ts">
	import { onMount } from 'svelte';
	import { api, ApiError, newId, type Task } from '#lib/api.js';
	import { changes, flush, outbox, snapshot, type Pending } from '#lib/outbox.js';

	const INBOX = 'Boîte de réception';

	type Row = { id: string; title: string; project: string; mail: string | null; pending: boolean };

	let phase = $state<'loading' | 'login' | 'app'>('loading');
	let online = $state(true);
	let needsLogin = $state(false);
	let tasks = $state<Task[]>([]);
	let pending = $state<Pending[]>([]);
	let hidden = $state<Set<string>>(new Set());
	let draft = $state('');
	let password = $state('');
	let loginError = $state('');
	let busy = $state(false);
	let bridge = $state(false);
	let captureInput: HTMLInputElement | undefined = $state();

	let rows = $derived.by(() => {
		const list: Row[] = [
			...pending.map((p) => ({ id: p.id, title: p.title, project: INBOX, mail: p.mail_message_id ?? null, pending: true })),
			...tasks
				.filter((t) => !pending.some((p) => p.id === t.id))
				.map((t) => ({ id: t.id, title: t.title, project: t.project_name || INBOX, mail: t.mail_message_id, pending: false }))
		].filter((r) => !hidden.has(r.id));
		const groups = new Map<string, Row[]>();
		for (const row of list) {
			if (!groups.has(row.project)) groups.set(row.project, []);
			groups.get(row.project)!.push(row);
		}
		// Inbox first: it holds what still needs sorting.
		return [...groups.entries()].sort(([a], [b]) => (a === INBOX ? -1 : b === INBOX ? 1 : a.localeCompare(b, 'fr')));
	});

	let status = $derived.by(() => {
		const waiting = pending.length;
		if (needsLogin) return 'Reconnecte-toi pour envoyer tes saisies';
		if (!online && waiting) return `Hors connexion, ${waiting} ${waiting > 1 ? 'saisies' : 'saisie'} en attente d’envoi`;
		if (!online) return 'Hors connexion';
		if (waiting) return `Envoi de ${waiting} ${waiting > 1 ? 'saisies' : 'saisie'}…`;
		return 'À jour';
	});

	async function sync(): Promise<void> {
		const result = await flush();
		pending = await outbox.list();
		if (result === 'unauthenticated') {
			needsLogin = true;
			phase = 'login';
			return;
		}
		if (result === 'offline') {
			online = false;
			return;
		}
		try {
			const fresh = await api.tasks();
			tasks = fresh;
			hidden = new Set([...hidden].filter((id) => fresh.some((t) => t.id === id)));
			online = true;
			needsLogin = false;
			await snapshot.save($state.snapshot(tasks));
		} catch (err) {
			if (err instanceof ApiError && err.status === 401) {
				needsLogin = true;
				phase = 'login';
			} else {
				online = false;
			}
		}
	}

	async function start(): Promise<void> {
		tasks = (await snapshot.load()) ?? [];
		pending = await outbox.list();
		try {
			const { authenticated } = await api.session();
			if (!authenticated) {
				phase = 'login';
				return;
			}
			phase = 'app';
			await sync();
		} catch {
			// Offline: work from the snapshot; captures wait in the outbox.
			online = false;
			phase = 'app';
		}
	}

	async function capture(event: SubmitEvent): Promise<void> {
		event.preventDefault();
		const title = draft.trim();
		if (!title) return;
		// Clear the field before any await: text typed right after Enter must not be lost.
		draft = '';
		captureInput?.focus();
		const item: Pending = { id: newId(), title, queued_at: new Date().toISOString() };
		pending = [...pending, item];
		await outbox.add(item);
		void sync();
	}

	async function markDone(row: Row): Promise<void> {
		hidden = new Set([...hidden, row.id]);
		if (row.pending) {
			// Never reached the server: simply drop it.
			await outbox.remove(row.id);
			pending = await outbox.list();
			return;
		}
		await changes.add({ id: row.id, change: 'done', queued_at: new Date().toISOString() });
		void sync();
	}

	async function login(event: SubmitEvent): Promise<void> {
		event.preventDefault();
		busy = true;
		loginError = '';
		try {
			await api.login(password);
			password = '';
			needsLogin = false;
			phase = 'app';
			await sync();
		} catch (err) {
			if (err instanceof ApiError && err.status === 401) loginError = 'Mot de passe incorrect.';
			else if (err instanceof ApiError && err.status === 429) loginError = 'Trop d’essais. Réessaie dans un quart d’heure.';
			else loginError = 'Serveur injoignable. Vérifie ta connexion.';
		} finally {
			busy = false;
		}
	}

	async function logout(): Promise<void> {
		try {
			await api.logout();
		} finally {
			phase = 'login';
		}
	}

	function openMail(messageId: string): void {
		// Handled by the Thunderbird extension's content script (see thunderbird/bridge.js).
		window.postMessage({ source: 'pige-web', type: 'open-mail', messageId }, window.location.origin);
	}

	onMount(() => {
		const detect = () => (bridge = document.documentElement.dataset.pigeThunderbird === '1');
		detect();
		window.addEventListener('pige-bridge-ready', detect);
		const goOnline = () => void sync();
		const goOffline = () => (online = false);
		window.addEventListener('online', goOnline);
		window.addEventListener('offline', goOffline);
		const timer = setInterval(() => {
			if (phase === 'app' && (pending.length || !online)) void sync();
		}, 30_000);
		void start();
		return () => {
			window.removeEventListener('pige-bridge-ready', detect);
			window.removeEventListener('online', goOnline);
			window.removeEventListener('offline', goOffline);
			clearInterval(timer);
		};
	});
</script>

<div class="page">
	<header>
		<h1>P.IGE</h1>
		{#if phase === 'app'}
			<p class="status" class:warn={!online || needsLogin} role="status">{status}</p>
		{/if}
	</header>

	{#if phase === 'loading'}
		<p class="quiet">Chargement…</p>
	{:else if phase === 'login'}
		<form class="login" onsubmit={login}>
			<h2>Connexion</h2>
			{#if pending.length}
				<p class="quiet">
					{pending.length}
					{pending.length > 1 ? 'saisies attendent' : 'saisie attend'} d’être envoyées. Elles partiront après la
					connexion.
				</p>
			{/if}
			<label for="password">Mot de passe</label>
			<input id="password" type="password" autocomplete="current-password" bind:value={password} required />
			{#if loginError}<p class="error" role="alert">{loginError}</p>{/if}
			<button class="primary" type="submit" disabled={busy}>Se connecter</button>
		</form>
	{:else}
		<form class="capture" onsubmit={capture}>
			<label class="visually-hidden" for="capture">Nouvelle tâche</label>
			<div class="field">
				<div class="inputwrap">
				<input
					id="capture"
					bind:this={captureInput}
					bind:value={draft}
					placeholder="Noter une tâche"
					autocomplete="off"
					enterkeyhint="done"
					maxlength="500"
				/>
					<div class="tape" aria-hidden="true"></div>
				</div>
				<button class="primary" type="submit" disabled={!draft.trim()}>Ajouter</button>
			</div>
		</form>

		{#if rows.length === 0}
			<p class="empty">Rien d’ouvert. Note la prochaine chose à faire, elle arrivera dans la boîte de réception.</p>
		{/if}

		{#each rows as [project, items] (project)}
			<section>
				<h2>{project} <span class="count">{items.length}</span></h2>
				<ul>
					{#each items as row (row.id)}
						<li class:pending={row.pending}>
							<button class="check" onclick={() => markDone(row)} aria-label={`Marquer « ${row.title} » comme faite`}></button>
							<div class="body">
								<span class="title">{row.title}</span>
								{#if row.pending || row.mail}
									<span class="meta">
										{#if row.pending}<span class="waiting">En attente d’envoi</span>{/if}
										{#if row.mail}
											{#if bridge}
												<button class="link" onclick={() => openMail(row.mail!)}>Ouvrir le mail</button>
											{:else}
												<span>Liée à un mail</span>
											{/if}
										{/if}
									</span>
								{/if}
							</div>
						</li>
					{/each}
				</ul>
			</section>
		{/each}

		<footer>
			<button class="link" onclick={logout}>Se déconnecter</button>
		</footer>
	{/if}
</div>

<style>
	.page {
		max-width: 40rem;
		margin: 0 auto;
		padding: max(env(safe-area-inset-top), 20px) var(--gutter) 48px;
	}

	header {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 12px;
		margin-bottom: 20px;
	}

	h1 {
		margin: 0;
		font-size: var(--step-2);
		font-weight: 700;
		letter-spacing: -0.01em;
	}

	.status {
		margin: 0;
		font-size: var(--step--1);
		color: var(--muted);
		text-align: right;
	}

	.status.warn {
		color: var(--pending);
	}

	/* Capture: the field sits on a graduated tape, the app's signature. */
	.capture {
		margin-bottom: 28px;
	}

	.field {
		display: flex;
		gap: 8px;
	}

	.inputwrap {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
	}

	.field input {
		width: 100%;
		padding: 14px 14px;
		font-size: var(--step-1);
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: var(--radius-field) var(--radius-field) 0 0;
		border-bottom: none;
	}

	.field input::placeholder {
		color: var(--muted);
	}

	.tape {
		height: 14px;
		background-color: var(--tape);
		background-image:
			repeating-linear-gradient(to right, var(--tape-tick) 0 2px, transparent 2px 60px),
			repeating-linear-gradient(to right, var(--tape-tick) 0 1px, transparent 1px 12px);
		background-size:
			100% 9px,
			100% 5px;
		background-repeat: no-repeat;
		border-radius: 0 0 4px 4px;
	}

	.field .primary {
		align-self: stretch;
	}

	.primary {
		padding: 0 18px;
		min-height: 48px;
		border: none;
		border-radius: var(--radius-field);
		background: var(--accent);
		color: var(--accent-ink);
		font-weight: 700;
		cursor: pointer;
	}

	.primary:disabled {
		opacity: 0.45;
		cursor: default;
	}

	section {
		margin-top: 24px;
	}

	h2 {
		margin: 0 0 6px;
		font-size: var(--step-0);
		font-weight: 700;
	}

	.count {
		font-weight: 400;
		color: var(--muted);
	}

	ul {
		list-style: none;
		margin: 0;
		padding: 0;
		border-top: 1px solid var(--line);
	}

	li {
		display: flex;
		gap: 12px;
		align-items: flex-start;
		padding: 12px 0;
		border-bottom: 1px solid var(--line);
	}

	.check {
		flex: none;
		width: 26px;
		height: 26px;
		margin-top: 1px;
		border: 2px solid var(--muted);
		border-radius: 50%;
		background: transparent;
		cursor: pointer;
	}

	.check:hover {
		border-color: var(--accent);
	}

	.body {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}

	.title {
		overflow-wrap: anywhere;
	}

	.meta {
		display: flex;
		gap: 12px;
		font-size: var(--step--1);
		color: var(--muted);
	}

	.pending .title {
		color: var(--muted);
	}

	.waiting {
		color: var(--pending);
	}

	.link {
		padding: 0;
		border: none;
		background: none;
		color: var(--accent);
		text-decoration: underline;
		text-underline-offset: 3px;
		cursor: pointer;
		font-size: var(--step--1);
	}

	.empty,
	.quiet {
		color: var(--muted);
		max-width: 34em;
	}

	.login {
		display: flex;
		flex-direction: column;
		gap: 10px;
		max-width: 24rem;
	}

	.login h2 {
		font-size: var(--step-1);
	}

	.login input {
		padding: 12px;
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
	}

	.error {
		margin: 0;
		color: var(--danger);
	}

	footer {
		margin-top: 40px;
	}

	.visually-hidden {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip-path: inset(50%);
		white-space: nowrap;
	}
</style>
