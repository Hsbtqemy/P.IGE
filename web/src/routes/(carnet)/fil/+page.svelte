<script lang="ts">
	// « Lire le fil »: every journal entry of a project (with its sub-projects), a space, a
	// person or a tag, in full, newest first. /fil?projet=… | espace=… | personne=… | etiquette=…
	import { page } from '$app/state';
	import { v2, type Entry } from '#lib/api2.js';
	import EntryThread from '#lib/carnet/EntryThread.svelte';
	import { carnet, failure, projectOf, spaceOf } from '#lib/carnet/state.svelte.js';

	const PAGE = 100;
	type Filter = 'all' | 'decision' | 'meeting' | 'mail';

	let entries = $state<Entry[] | null>(null);
	let more = $state(false);
	let loadingMore = $state(false);
	let message = $state('');
	let filter = $state<Filter>('all');
	let tagName = $state('');

	let params = $derived(page.url.searchParams);
	let scope = $derived.by(() => {
		const id = (k: string) => params.get(k) ?? '';
		if (id('projet')) return { key: 'project_id', id: id('projet'), back: `/projets/${id('projet')}` } as const;
		if (id('espace')) return { key: 'space_id', id: id('espace'), back: `/espaces/${id('espace')}` } as const;
		if (id('personne')) return { key: 'person_id', id: id('personne'), back: `/personnes/${id('personne')}` } as const;
		if (id('etiquette')) return { key: 'tag_id', id: id('etiquette'), back: `/etiquettes/${id('etiquette')}` } as const;
		return null;
	});
	let name = $derived.by(() => {
		if (!scope) return '';
		if (scope.key === 'project_id') return projectOf(scope.id)?.name ?? 'Projet';
		if (scope.key === 'space_id') return spaceOf(scope.id)?.name ?? 'Espace';
		if (scope.key === 'person_id') return carnet.people.find((p) => p.id === scope.id)?.display_name ?? 'Personne';
		return tagName ? `#${tagName}` : 'Étiquette';
	});

	async function fetchPage(offset: number): Promise<Entry[]> {
		if (!scope) return [];
		return v2.timeline({ [scope.key]: scope.id, limit: PAGE, offset });
	}

	$effect(() => {
		const current = scope;
		entries = null;
		message = '';
		filter = 'all';
		if (!current) return;
		if (current.key === 'tag_id') v2.tag(current.id).then((t) => (tagName = t.name)).catch(() => {});
		fetchPage(0)
			.then((list) => {
				if (current !== scope) return;
				entries = list;
				more = list.length === PAGE;
			})
			.catch((err) => (message = failure(err, 'Fil non chargé : ')));
	});

	async function loadMore() {
		if (!entries) return;
		loadingMore = true;
		try {
			const next = await fetchPage(entries.length);
			entries = [...entries, ...next];
			more = next.length === PAGE;
		} catch (err) {
			message = failure(err, 'Suite non chargée : ');
		} finally {
			loadingMore = false;
		}
	}

	const FILTERS: { value: Filter; label: string }[] = [
		{ value: 'all', label: 'Tout' },
		{ value: 'decision', label: 'Décisions' },
		{ value: 'meeting', label: 'Réunions' },
		{ value: 'mail', label: 'Mails' }
	];
	let shown = $derived(
		(entries ?? []).filter((e) =>
			filter === 'all' ? true : filter === 'mail' ? e.source === 'mail' : e.kind === filter
		)
	);
</script>

<svelte:head><title>Fil · {name} · P.IGE</title></svelte:head>

<div class="wrap">
	{#if !scope}
		<p>Choisis un projet, une personne ou une étiquette, puis « Lire le fil ».</p>
	{:else}
		<header>
			<a class="back" href={scope.back}>‹ {name}</a>
			<h1>Le fil <span class="of">{name}</span></h1>
			<div class="chips" role="group" aria-label="Filtrer">
				{#each FILTERS as f (f.value)}
					<button class="chip" class:on={filter === f.value} aria-pressed={filter === f.value} onclick={() => (filter = f.value)}>{f.label}</button>
				{/each}
			</div>
		</header>
		{#if message}<p class="message" role="alert">{message}</p>{/if}
		{#if !entries}
			<p class="muted">Chargement…</p>
		{:else}
			<EntryThread
				entries={shown}
				showPlace={scope.key !== 'project_id' || shown.some((e) => e.project_id !== scope?.id)}
				onchanged={(u) => (entries = (entries ?? []).map((e) => (e.id === u.id ? u : e)))}
			/>
			{#if !shown.length}<p class="muted">Rien {filter === 'all' ? 'dans ce fil' : 'de ce genre ici'}.</p>{/if}
			{#if more}
				<button class="btn" disabled={loadingMore} onclick={loadMore}>{loadingMore ? 'Chargement…' : 'Plus anciens'}</button>
			{/if}
		{/if}
	{/if}
</div>

<style>
	.wrap {
		padding: 22px 32px 48px;
		display: flex;
		flex-direction: column;
		gap: 14px;
		max-width: 820px;
	}
	header {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.back {
		font-size: 0.875rem;
		color: var(--muted);
	}
	h1 {
		font-size: 2rem;
	}
	.of {
		font-style: italic;
		font-weight: 400;
		color: var(--muted);
	}
	.chips {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.chip {
		padding: 4px 12px;
		font: inherit;
		font-size: 0.8125rem;
		color: var(--ink);
		background: transparent;
		border: 1px solid var(--line);
		border-radius: 999px;
		cursor: pointer;
	}
	.chip.on {
		color: var(--accent-ink);
		background: var(--accent);
		border-color: var(--accent);
	}
	.muted {
		color: var(--muted);
	}
	.message {
		color: var(--warn);
	}
	.btn {
		align-self: flex-start;
	}
	@media (max-width: 600px) {
		.wrap {
			padding: 16px;
		}
	}
</style>
