<script lang="ts">
	import { goto } from '$app/navigation';
	import { v2, type Entry } from '#lib/api2.js';
	import { TEMPLATES } from '#lib/carnet/writing/export.js';
	import { carnet, defaultSpace, failure, longDate, placeName, todayIso } from '#lib/carnet/state.svelte.js';

	let texts = $state<Entry[] | null>(null);
	let message = $state('');
	let title = $state('');
	let place = $state('');
	let template = $state('vide');
	let creating = $state(false);

	$effect(() => {
		v2.timeline({ source: 'writing', limit: 200 })
			.then((t) => (texts = t))
			.catch((err) => (message = failure(err, 'Textes non chargés : ')));
	});

	async function create(event: SubmitEvent) {
		event.preventDefault();
		const name = title.trim();
		if (!name || creating) return;
		const chosen = TEMPLATES.find((t) => t.id === template) ?? TEMPLATES[0];
		const where = place.startsWith('p:')
			? { project_id: place.slice(2) }
			: { space_id: place.startsWith('s:') ? place.slice(2) : defaultSpace()?.id };
		creating = true;
		message = '';
		try {
			const day = todayIso();
			const entry = await v2.createEntry({
				...where,
				entry_date: day,
				title: name,
				kind: chosen.kind,
				body: chosen.body(name, longDate(day).toLocaleLowerCase('fr')),
				source: 'writing'
			});
			await goto(`/ecrire/${entry.id}`);
		} catch (err) {
			message = failure(err, 'Texte non créé : ');
		} finally {
			creating = false;
		}
	}

	function words(text: string): number {
		return text.split(/\s+/).filter((w) => /[\p{L}\p{N}]/u.test(w)).length;
	}
</script>

<svelte:head><title>Écrire · P.IGE</title></svelte:head>

<div class="wrap">
	<h1>Écrire</h1>
	<p class="hint">Les textes longs : comptes rendus, notes de cadrage, rapports. Ils s’enregistrent pendant que tu écris et gardent leurs versions.</p>

	<form class="new" onsubmit={create}>
		<input bind:value={title} placeholder="Titre du nouveau texte" aria-label="Titre du nouveau texte" required />
		<select bind:value={template} aria-label="Modèle">
			{#each TEMPLATES as t (t.id)}<option value={t.id}>{t.label}</option>{/each}
		</select>
		<select bind:value={place} aria-label="Projet ou espace">
			<option value="">Ranger dans « {defaultSpace()?.name ?? 'À trier'} »</option>
			{#each carnet.tree?.spaces ?? [] as space (space.id)}
				<optgroup label={space.name}>
					<option value="s:{space.id}">{space.name} (sans projet)</option>
					{#each space.projects as project (project.id)}<option value="p:{project.id}">{project.name}</option>{/each}
				</optgroup>
			{/each}
		</select>
		<button class="btn primary" disabled={creating || !title.trim()}>Commencer</button>
	</form>

	{#if message}<p class="message" role="alert">{message}</p>{/if}

	{#if !texts}
		<p class="muted">Chargement…</p>
	{:else}
		<ul>
			{#each texts as text (text.id)}
				<li>
					<a href="/ecrire/{text.id}">
						<b>{text.title || 'Sans titre'}</b>
						<small>{placeName(text)} · {longDate(text.entry_date).toLocaleLowerCase('fr')} · {words(text.body)} mots</small>
					</a>
				</li>
			{:else}
				<li class="muted">Aucun texte pour l’instant.</li>
			{/each}
		</ul>
	{/if}
</div>

<style>
	.wrap {
		padding: 22px 32px 48px;
		display: flex;
		flex-direction: column;
		gap: 14px;
		max-width: 880px;
	}
	h1 {
		font-size: 1.875rem;
		margin: 0;
	}
	.hint,
	.muted,
	small {
		font-size: 0.875rem;
		color: var(--muted);
	}
	.hint {
		margin: 0;
	}
	.new {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		padding: 12px;
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 10px;
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
	.new input {
		flex: 1 1 100%;
		font-size: 1.0625rem;
	}
	.new select {
		flex: 1 1 200px;
	}
	.message {
		margin: 0;
		padding: 8px 12px;
		color: var(--warn);
		background: var(--warn-soft);
		border-radius: 8px;
	}
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
		border-top: var(--rule);
	}
	li {
		border-bottom: 1px solid var(--line);
	}
	li.muted {
		padding: 10px 0;
	}
	li a {
		display: flex;
		flex-direction: column;
		padding: 10px 4px;
		text-decoration: none;
	}
	li a b {
		font-family: var(--serif);
		font-size: 1.125rem;
	}
	li a:hover {
		background: var(--softer);
	}
	@media (max-width: 600px) {
		.wrap {
			padding: 16px;
		}
	}
</style>
