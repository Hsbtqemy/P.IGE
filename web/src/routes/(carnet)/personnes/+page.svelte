<script lang="ts">
	import { goto } from '$app/navigation';
	import { v2, type Person, type Tag } from '#lib/api2.js';
	import { fold } from '#lib/feuillet.js';
	import { carnet, failure } from '#lib/carnet/state.svelte.js';

	let query = $state('');
	let sort = $state<'name' | 'recent'>('name');
	let tag = $state<Tag | null>(null);
	let tagged = $state<Person[] | null>(null);
	let allTags = $state<Tag[]>([]);
	let newName = $state('');
	let message = $state('');

	$effect(() => {
		v2.tags()
			.then((t) => (allTags = t.filter((x) => (x.uses ?? 0) > 0)))
			.catch((err) => (message = failure(err, 'Étiquettes non chargées : ')));
	});

	async function pickTag(t: Tag | null) {
		tag = t;
		tagged = null;
		if (!t) return;
		try {
			const people = await v2.peopleWithTag(t.id);
			if (tag?.id === t.id) tagged = people;
		} catch (err) {
			message = failure(err, 'Filtre non appliqué : ');
		}
	}

	let shown = $derived.by(() => {
		const base = tag ? (tagged ?? []) : carnet.people;
		const lastOf = new Map(carnet.people.map((p) => [p.id, p.last_exchange ?? '']));
		const words = fold(query).split(' ').filter(Boolean);
		const list = base.filter((p) => {
			const hay = fold(`${p.display_name} ${p.organisation ?? ''} ${p.role ?? ''} ${p.email ?? ''}`);
			return words.every((w) => hay.includes(w));
		});
		return list.sort((a, b) =>
			sort === 'recent'
				? (lastOf.get(b.id) ?? '').localeCompare(lastOf.get(a.id) ?? '') || a.display_name.localeCompare(b.display_name, 'fr')
				: a.display_name.localeCompare(b.display_name, 'fr')
		);
	});

	function lastLabel(p: Person): string {
		const iso = carnet.people.find((x) => x.id === p.id)?.last_exchange;
		if (!iso) return '';
		return new Date(`${iso}T12:00:00`).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' });
	}

	async function add(event: SubmitEvent) {
		event.preventDefault();
		const name = newName.trim();
		if (!name) return;
		message = '';
		try {
			const person = await v2.person(name);
			if (!carnet.people.some((p) => p.id === person.id)) carnet.people = [...carnet.people, person];
			newName = '';
			await goto(`/personnes/${person.id}`);
		} catch (err) {
			message = failure(err, 'Personne non créée : ');
		}
	}
</script>

<svelte:head><title>Personnes · P.IGE</title></svelte:head>

<div class="wrap">
	<header>
		<h1>Personnes <small>{carnet.people.length}</small></h1>
		<div class="tools">
			<input type="search" bind:value={query} placeholder="Chercher un nom, un laboratoire…" aria-label="Chercher une personne" />
			<select bind:value={sort} aria-label="Trier">
				<option value="name">Par nom</option>
				<option value="recent">Dernier échange</option>
			</select>
		</div>
		{#if allTags.length}
			<div class="tags" role="group" aria-label="Filtrer par étiquette">
				<button class="chip" class:on={!tag} aria-pressed={!tag} onclick={() => pickTag(null)}>Toutes</button>
				{#each allTags as t (t.id)}
					<button class="chip" class:on={tag?.id === t.id} aria-pressed={tag?.id === t.id} onclick={() => pickTag(t)}>
						#{t.name}
					</button>
				{/each}
			</div>
		{/if}
	</header>

	{#if message}<p class="message" role="alert">{message}</p>{/if}

	<ul class="people">
		{#each shown as person (person.id)}
			<li>
				<a href="/personnes/{person.id}">
					<span class="name">{person.display_name}</span>
					<small>{[person.role, person.organisation].filter(Boolean).join(' · ')}</small>
					<small class="last">{lastLabel(person)}</small>
				</a>
			</li>
		{:else}
			<li class="muted">{tag && !tagged ? 'Chargement…' : 'Personne ne correspond.'}</li>
		{/each}
	</ul>

	<form class="new" onsubmit={add}>
		<input bind:value={newName} placeholder="+ Ajouter une personne (NOM Prénom)" aria-label="Ajouter une personne" />
	</form>
</div>

<style>
	.wrap {
		padding: 22px 32px 48px;
		display: flex;
		flex-direction: column;
		gap: 14px;
		max-width: 880px;
	}
	header {
		display: flex;
		flex-direction: column;
		gap: 10px;
	}
	h1 {
		font-size: 1.875rem;
		margin: 0;
	}
	small,
	.muted {
		font-family: var(--sans);
		font-weight: 400;
		font-size: 0.875rem;
		color: var(--muted);
	}
	.tools {
		display: flex;
		gap: 8px;
	}
	input,
	select {
		font: inherit;
		color: var(--ink);
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 6px;
		padding: 6px 10px;
		min-width: 0;
	}
	.tools input {
		flex: 1;
	}
	.tags {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.chip {
		min-height: 30px;
		padding: 0 10px;
		font: inherit;
		font-size: 0.8125rem;
		color: var(--ink);
		background: transparent;
		border: 1px solid var(--line);
		border-radius: 15px;
	}
	.chip.on {
		font-weight: 700;
		background: var(--soft);
		border-color: var(--accent);
	}
	.message {
		margin: 0;
		padding: 8px 12px;
		color: var(--warn);
		background: var(--warn-soft);
		border-radius: 8px;
	}
	.people {
		list-style: none;
		margin: 0;
		padding: 0;
		border-top: var(--rule);
	}
	.people li {
		border-bottom: 1px solid var(--line);
	}
	.people li.muted {
		padding: 10px 0;
	}
	.people a {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto;
		gap: 12px;
		align-items: baseline;
		padding: 9px 4px;
		text-decoration: none;
	}
	.people a:hover {
		background: var(--softer);
	}
	.name {
		font-weight: 700;
	}
	.last {
		font-variant-numeric: tabular-nums;
	}
	.new input {
		width: 100%;
		box-sizing: border-box;
		background: transparent;
		border-style: dashed;
	}
	.new input:focus {
		background: var(--surface);
		border-style: solid;
	}
	@media (max-width: 600px) {
		.wrap {
			padding: 16px;
		}
		.people a {
			grid-template-columns: minmax(0, 1fr) auto;
		}
		.people a small:not(.last) {
			grid-column: 1 / -1;
			grid-row: 2;
		}
	}
</style>
