<script lang="ts">
	// « + » on a day of the Agenda: an event of one's own (title, time, place). It is a journal
	// entry shown as planned; its time counts only once « Compter » is clicked.
	import { tick } from 'svelte';
	import { v2, type Entry } from '../api2.js';
	import { carnet, defaultSpace, failure } from './state.svelte.js';
	import { parseRange } from './timerange.js';

	let { day, onadded }: { day: string; onadded: (entry: Entry) => void } = $props();

	let open = $state(false);
	let title = $state('');
	let when = $state('');
	let place = $state('');
	let busy = $state(false);
	let message = $state('');
	let input: HTMLInputElement | undefined = $state();

	async function start() {
		const s = defaultSpace();
		place ||= s ? `s:${s.id}` : '';
		open = true;
		await tick();
		input?.focus();
	}

	async function add(event: SubmitEvent) {
		event.preventDefault();
		const text = title.trim();
		const range = parseRange(when);
		if (!text || !place) return;
		if (!range) {
			message = 'Heure : par exemple 9h30-11h, 14h, ou rien pour la journée.';
			return;
		}
		busy = true;
		message = '';
		try {
			const entry = await v2.createEntry({
				entry_date: day,
				...(place.startsWith('p:') ? { project_id: place.slice(2) } : { space_id: place.slice(2) }),
				kind: 'meeting',
				title: text,
				body: text,
				start_time: range.start,
				end_time: range.end,
				source: 'journal',
				agenda: true
			});
			title = '';
			when = '';
			open = false;
			onadded(entry);
		} catch (err) {
			message = failure(err, 'Événement non ajouté : ');
		} finally {
			busy = false;
		}
	}
</script>

{#if open}
	<form class="add" onsubmit={add}>
		<input bind:this={input} bind:value={title} placeholder="Titre" aria-label="Titre de l’événement" required
			onkeydown={(e) => e.key === 'Escape' && (open = false)} />
		<input class="when" bind:value={when} placeholder="9h30-11h" aria-label="Heure (vide : journée)"
			onkeydown={(e) => e.key === 'Escape' && (open = false)} />
		<select bind:value={place} aria-label="Projet ou espace" required>
			{#each carnet.tree?.spaces ?? [] as s (s.id)}
				<optgroup label={s.name}>
					<option value="s:{s.id}">{s.name} (sans projet)</option>
					{#each s.projects as p (p.id)}<option value="p:{p.id}">{p.name}</option>{/each}
				</optgroup>
			{/each}
		</select>
		<button class="btn primary" disabled={busy || !title.trim()}>Ajouter</button>
		<button type="button" class="btn" onclick={() => (open = false)}>Annuler</button>
		{#if message}<small class="warn" role="alert">{message}</small>{/if}
	</form>
{:else}
	<button class="plus" onclick={start} title="Ajouter un événement ce jour-là">+ ajouter</button>
{/if}

<style>
	.plus {
		align-self: flex-start;
		margin: 2px 0;
		padding: 2px 4px;
		border: 0;
		border-radius: 6px;
		background: none;
		font: inherit;
		font-family: var(--sans);
		font-size: 0.8125rem;
		color: var(--muted);
		opacity: 0.7;
		cursor: pointer;
	}
	.plus:hover,
	.plus:focus-visible {
		opacity: 1;
		color: var(--accent);
		background: var(--soft);
	}
	.add {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		align-items: center;
		padding: 8px 0 8px 12px;
		border-left: 3px solid var(--accent);
		border-bottom: 1px solid var(--line);
		font-family: var(--sans);
	}
	input,
	select {
		font: inherit;
		font-size: 0.875rem;
		padding: 4px 8px;
		color: var(--ink);
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 6px;
	}
	input:first-child {
		flex: 1;
		min-width: 160px;
	}
	.when {
		width: 100px;
	}
	.warn {
		flex-basis: 100%;
		color: var(--warn);
	}
</style>
