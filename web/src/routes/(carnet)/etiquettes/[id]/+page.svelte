<script lang="ts">
	import { page } from '$app/state';
	import { ApiError } from '#lib/api.js';
	import { v2, type Entry, type TagView } from '#lib/api2.js';
	import EntryList from '#lib/carnet/EntryList.svelte';
	import TaskList from '#lib/carnet/TaskList.svelte';
	import { failure, reload } from '#lib/carnet/state.svelte.js';

	let id = $derived(page.params.id ?? '');
	let tag = $state<TagView | null>(null);
	let entries = $state<Entry[]>([]);
	let loadError = $state('');
	let message = $state('');

	$effect(() => {
		const current = id;
		tag = null;
		loadError = '';
		Promise.all([v2.tag(current), v2.timeline({ tag_id: current, limit: 100 })])
			.then(([t, e]) => {
				if (current !== id) return;
				tag = t;
				entries = e;
			})
			.catch((err) => {
				if (current !== id) return;
				loadError = err instanceof ApiError && err.status === 404 ? 'Étiquette introuvable.' : failure(err, 'Étiquette non chargée : ');
			});
	});

	async function pin() {
		if (!tag) return;
		message = '';
		try {
			const saved = await v2.pinTag(tag.id, !tag.pinned);
			tag = { ...tag, pinned: saved.pinned };
			reload().catch(() => {});
		} catch (err) {
			message = failure(err, 'Épinglage non modifié : ');
		}
	}
</script>

<svelte:head><title>#{tag?.name ?? 'Étiquette'} · P.IGE</title></svelte:head>

<div class="wrap">
	{#if loadError}
		<p>{loadError} <a href="/etiquettes">Toutes les étiquettes</a></p>
	{:else if tag}
		<header>
			<a class="crumbs" href="/etiquettes">‹ Étiquettes</a>
			<div class="title">
				<h1><span class="hash">#</span>{tag.name}</h1>
				<button class="pin" class:on={tag.pinned} aria-pressed={tag.pinned} onclick={pin}>{tag.pinned ? 'Épinglée' : 'Épingler'}</button>
			</div>
		</header>
		{#if message}<p class="message" role="alert">{message}</p>{/if}
		<div class="cols">
			<section>
				<h2>Personnes <small>{tag.people.length || ''}</small></h2>
				{#each tag.people as person (person.id)}
					<a class="person" href="/personnes/{person.id}">
						<b>{person.display_name}</b>
						<small>{[person.role, person.organisation].filter(Boolean).join(' · ')}</small>
					</a>
				{:else}
					<p class="muted">Personne.</p>
				{/each}
			</section>
			<section>
				<h2>Tâches ouvertes <small>{tag.tasks.length || ''}</small></h2>
				<TaskList tasks={tag.tasks} empty="Aucune tâche ouverte." />
			</section>
			<section class="wide">
				<h2>Journal <small>{entries.length || ''}</small></h2>
				<EntryList {entries} showPlace empty="Aucun paragraphe." />
			</section>
		</div>
	{:else}
		<p>Chargement…</p>
	{/if}
</div>

<style>
	.wrap {
		padding: 22px 32px 48px;
		display: flex;
		flex-direction: column;
		gap: 14px;
	}
	.crumbs {
		font-size: 0.875rem;
		color: var(--muted);
	}
	.title {
		display: flex;
		align-items: center;
		gap: 14px;
	}
	h1 {
		font-size: 1.875rem;
		margin: 0;
	}
	.hash {
		color: var(--accent);
	}
	.pin {
		min-height: 30px;
		padding: 0 12px;
		font: inherit;
		font-size: 0.8125rem;
		color: var(--muted);
		background: transparent;
		border: 1px solid var(--line);
		border-radius: 15px;
	}
	.pin.on {
		font-weight: 700;
		color: var(--ink);
		background: var(--soft);
		border-color: var(--accent);
	}
	small,
	.muted {
		font-family: var(--sans);
		font-weight: 400;
		font-size: 0.875rem;
		color: var(--muted);
	}
	.message {
		margin: 0;
		padding: 8px 12px;
		color: var(--warn);
		background: var(--warn-soft);
		border-radius: 8px;
	}
	.cols {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
		gap: 22px 32px;
		align-items: start;
	}
	.wide {
		grid-column: 1 / -1;
	}
	h2 {
		font-size: 1.125rem;
		padding-bottom: 4px;
		border-bottom: var(--rule);
		margin: 0;
	}
	.person {
		display: flex;
		flex-direction: column;
		padding: 8px 0;
		border-bottom: 1px solid var(--line);
		text-decoration: none;
	}
	@media (max-width: 800px) {
		.cols {
			grid-template-columns: 1fr;
		}
	}
	@media (max-width: 600px) {
		.wrap {
			padding: 16px;
		}
	}
</style>
