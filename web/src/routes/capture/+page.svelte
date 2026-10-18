<script lang="ts">
	import '@fontsource/newsreader/latin-600.css';
	import '#lib/carnet/carnet.css';
	import { onMount, tick } from 'svelte';
	import { api, ApiError } from '#lib/api.js';
	import { v2, type Person, type Tree } from '#lib/api2.js';
	import { cache, prepare, type Capture } from '#lib/carnet/capture.js';
	import Login from '#lib/carnet/Login.svelte';
	import { autoSync, dropRefused, outbox, queue, retryRefused, sync } from '#lib/carnet/outbox.svelte.js';
	import { read } from '#lib/feuillet.js';

	let tree = $state<Tree | null>(null);
	let people = $state<Pick<Person, 'display_name'>[]>([]);
	let phase = $state<'loading' | 'ready' | 'login' | 'first'>('loading');
	let online = $state(true);
	let text = $state('');
	let place = $state('');
	let notice = $state('');
	let field = $state<HTMLTextAreaElement | null>(null);

	async function start() {
		online = navigator.onLine;
		const [cachedTree, cachedPeople, wasSignedIn] = await Promise.all([
			cache.tree().catch(() => null),
			cache.people().catch(() => []),
			cache.signedIn().catch(() => false)
		]);
		tree = cachedTree;
		people = cachedPeople;
		try {
			const session = await api.session();
			if (!session.authenticated) {
				phase = 'login';
				return;
			}
			const [t, p] = await Promise.all([v2.tree(), v2.people()]);
			tree = t;
			people = p;
			online = true;
			void cache.save(t, p).catch(() => {});
			phase = 'ready';
		} catch (err) {
			if (err instanceof ApiError && err.status === 401) {
				phase = 'login';
				return;
			}
			online = false;
			// Offline: notes can still be taken by someone who signed in here before.
			phase = wasSignedIn ? 'ready' : 'first';
		}
		await tick();
		field?.focus();
	}

	onMount(() => {
		void start();
		const stop = autoSync();
		const up = () => {
			online = true;
			if (phase !== 'ready') void start();
		};
		const down = () => (online = false);
		window.addEventListener('online', up);
		window.addEventListener('offline', down);
		return () => {
			stop();
			window.removeEventListener('online', up);
			window.removeEventListener('offline', down);
		};
	});

	let projects = $derived(tree?.spaces.flatMap((s) => s.projects) ?? []);
	let reading = $derived(text.trim() ? read(text, projects, people) : null);
	let defaultSpace = $derived(
		tree?.spaces.find((s) => s.name.toLocaleLowerCase('fr') === 'à trier') ?? tree?.spaces[0] ?? null
	);

	function placeName(c: Capture): string {
		const pid = c.target.project_id;
		if (pid) return projects.find((p) => p.id === pid)?.name ?? 'projet';
		return tree?.spaces.find((s) => s.id === c.target.space_id)?.name ?? 'À trier';
	}

	async function note(event?: Event) {
		event?.preventDefault();
		const body = text.trim();
		if (!body) return;
		const forced = place.startsWith('p:') ? { project_id: place.slice(2) } : place.startsWith('s:') ? { space_id: place.slice(2) } : null;
		const c = prepare(body, tree, people, { place: forced, fallbackSpace: defaultSpace?.id ?? null });
		if (!c.target.project_id && !c.target.space_id) {
			notice = 'Aucun espace connu sur ce téléphone : connecte-toi une fois avec du réseau.';
			return;
		}
		try {
			await queue(c);
		} catch {
			notice = 'Ce navigateur ne peut pas garder de notes (navigation privée ?). Rien n’a été enregistré.';
			return;
		}
		text = '';
		place = '';
		const result = await sync();
		const still = outbox.pending.some((p) => p.id === c.id);
		notice = !still
			? `Noté dans ${placeName(c)}.`
			: result === 'unauthenticated'
				? 'Gardé sur ce téléphone. Reconnecte-toi pour l’envoyer.'
				: 'Gardé sur ce téléphone : il partira au retour du réseau.';
		if (result === 'unauthenticated') phase = 'login';
		await tick();
		field?.focus();
	}

	function keys(event: KeyboardEvent) {
		if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) void note(event);
	}

	async function copy(t: string) {
		try {
			await navigator.clipboard.writeText(t);
			notice = 'Texte copié.';
		} catch {
			notice = 'Copie refusée par le navigateur.';
		}
	}

	function ago(iso: string): string {
		const d = new Date(iso);
		return d.toLocaleString('fr-FR', { weekday: 'short', hour: '2-digit', minute: '2-digit' });
	}

	// Notes kept on the phone have left: say so instead of the old « gardé » message.
	let waiting = 0;
	$effect(() => {
		const n = outbox.pending.length;
		if (n < waiting && n === 0 && notice.startsWith('Gardé')) notice = 'Tout est envoyé.';
		waiting = n;
	});
</script>

<svelte:head>
	<title>Noter · P.IGE</title>
	<meta name="theme-color" content="#7a2e3a" />
</svelte:head>

<div class="carnet">
	{#if phase === 'loading'}
		<p class="center">Chargement…</p>
	{:else if phase === 'login'}
		{#if outbox.pending.length}
			<p class="center small">{outbox.pending.length} note{outbox.pending.length > 1 ? 's' : ''} en attente sur ce téléphone : elles partiront après la connexion.</p>
		{/if}
		<Login onlogin={start} />
	{:else if phase === 'first'}
		<div class="center">
			<p>Pas de réseau, et ce téléphone n’a encore jamais été connecté à P.IGE.</p>
			<p class="small">Connecte-toi une première fois avec du réseau : ensuite, tu pourras noter même hors connexion.</p>
			<button class="btn" onclick={start}>Réessayer</button>
		</div>
	{:else}
		<main class="capture">
			<header>
				<a class="brand" href="/journal">P.IGE</a>
				<span class="state" class:off={!online}>
					<span class="dot" aria-hidden="true"></span>
					{online ? 'En ligne' : 'Hors connexion'}
				</span>
			</header>

			<form onsubmit={note}>
				<textarea
					bind:this={field}
					bind:value={text}
					onkeydown={keys}
					rows="6"
					placeholder="Noter… un nom de projet, @personne, #étiquette, [ ] tâche, « Décision : »"
					aria-label="Note"
				></textarea>
				{#if reading}
					<p class="reading">
						<span>→ {reading.project?.name ?? defaultSpace?.name ?? 'À trier'}</span>
						{#each reading.people as p (p)}<span class="chip-person">@{p}</span>{/each}
						{#each reading.tags as t (t)}<span class="chip-tag">#{t}</span>{/each}
						{#if reading.tasks.length}<span>{reading.tasks.length} tâche{reading.tasks.length > 1 ? 's' : ''}</span>{/if}
						{#if reading.kind === 'decision'}<span>décision</span>{/if}
					</p>
				{/if}
				<div class="row">
					<select bind:value={place} aria-label="Ranger dans">
						<option value="">Rangement automatique</option>
						{#each tree?.spaces ?? [] as space (space.id)}
							<optgroup label={space.name}>
								<option value="s:{space.id}">{space.name} (sans projet)</option>
								{#each space.projects as project (project.id)}<option value="p:{project.id}">{project.name}</option>{/each}
							</optgroup>
						{/each}
					</select>
					<button class="btn primary" disabled={!text.trim()}>Noter</button>
				</div>
			</form>

			{#if notice}<p class="notice" role="status">{notice}</p>{/if}

			{#if outbox.pending.length}
				<section>
					<h2>En attente d’envoi <small>{outbox.pending.length}</small></h2>
					{#each outbox.pending as c (c.id)}
						<div class="item">
							<span class="text">{c.text}</span>
							<small>{placeName(c)} · {ago(c.queued_at)}</small>
						</div>
					{/each}
					<button class="btn" onclick={() => sync()} disabled={outbox.syncing}>{outbox.syncing ? 'Envoi…' : 'Envoyer maintenant'}</button>
				</section>
			{/if}

			{#if outbox.refused.length}
				<section class="refused">
					<h2>Refusées par le serveur <small>{outbox.refused.length}</small></h2>
					{#each outbox.refused as r (r.id)}
						<div class="item">
							<span class="text">{r.text}</span>
							<small>{r.reason}</small>
							<span class="actions">
								<button class="btn" onclick={() => copy(r.text)}>Copier</button>
								<button class="btn" onclick={() => retryRefused(r)}>Réessayer</button>
								<button class="btn" onclick={() => confirm('Supprimer cette note de ce téléphone ?') && dropRefused(r.id)}>Supprimer</button>
							</span>
						</div>
					{/each}
				</section>
			{/if}

			<nav>
				<a href="/journal">Journal du jour</a>
				<a href="/journee">Ma journée</a>
			</nav>
		</main>
	{/if}
</div>

<style>
	.center {
		padding: 18vh 24px 0;
		text-align: center;
		max-width: 420px;
		margin: 0 auto;
	}
	.small,
	small {
		font-size: 0.875rem;
		color: var(--muted);
	}
	.capture {
		max-width: 640px;
		margin: 0 auto;
		padding: 14px 16px 40px;
		display: flex;
		flex-direction: column;
		gap: 14px;
	}
	header {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}
	.brand {
		font-family: var(--serif);
		font-size: 1.375rem;
		font-weight: 600;
		text-decoration: none;
	}
	.state {
		display: flex;
		align-items: center;
		gap: 6px;
		font-size: 0.875rem;
		color: var(--muted);
	}
	.dot {
		width: 9px;
		height: 9px;
		border-radius: 50%;
		background: #3d7a4f;
	}
	.off .dot {
		background: var(--warn);
	}
	.off {
		color: var(--warn);
		font-weight: 700;
	}
	form {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	textarea {
		width: 100%;
		box-sizing: border-box;
		padding: 12px;
		font: inherit;
		font-size: 1.0625rem;
		line-height: 1.5;
		color: var(--ink);
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 10px;
		resize: vertical;
	}
	textarea:focus {
		outline: 2px solid var(--accent);
		outline-offset: 1px;
	}
	.reading {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin: 0;
		font-size: 0.875rem;
		color: var(--muted);
	}
	.row {
		display: flex;
		gap: 8px;
	}
	select {
		flex: 1;
		min-width: 0;
		font: inherit;
		font-size: 0.9375rem;
		color: var(--ink);
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 8px;
		padding: 0 8px;
	}
	.row .btn {
		min-height: 44px;
		padding: 0 22px;
	}
	.notice {
		margin: 0;
		padding: 10px 12px;
		background: var(--soft);
		border-radius: 8px;
	}
	h2 {
		font-size: 1.0625rem;
		margin: 0 0 4px;
		padding-bottom: 4px;
		border-bottom: var(--rule);
	}
	h2 small {
		font-family: var(--sans);
		font-weight: 400;
	}
	section {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	section > .btn {
		align-self: flex-start;
	}
	.item {
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: 6px 0;
		border-bottom: 1px solid var(--line);
	}
	.text {
		white-space: pre-line;
		overflow-wrap: anywhere;
		display: -webkit-box;
		-webkit-line-clamp: 3;
		line-clamp: 3;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}
	.refused small {
		color: var(--warn);
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin-top: 4px;
	}
	nav {
		display: flex;
		gap: 16px;
		font-size: 0.875rem;
	}
	nav a {
		color: var(--muted);
	}
</style>
