<script lang="ts">
	// Something written ahead in the journal for this day (a training, leave, a meeting not in
	// any calendar): shown with the agenda, opened in the journal. The little bin marks it
	// cancelled (struck through, no time counted, kept as a trace); a second click restores it.
	import { v2, type Entry } from '../api2.js';
	import { failure, placeName } from './state.svelte.js';
	import { showRange } from './timerange.js';
	import NotesButton from './NotesButton.svelte';

	let { entry, onchanged }: { entry: Entry; onchanged?: (updated: Entry) => void } = $props();
	let title = $derived(entry.title || entry.body.split('\n').find((l) => l.trim())?.trim().slice(0, 120) || 'Sans titre');
	let busy = $state(false);
	let message = $state('');

	async function toggle() {
		busy = true;
		message = '';
		try {
			const updated = await v2.updateEntry(entry.id, { expected_revision: entry.revision, cancelled: !entry.cancelled });
			onchanged?.(updated);
		} catch (err) {
			message = failure(err, '');
		} finally {
			busy = false;
		}
	}
</script>

<div class="planned" class:cancelled={entry.cancelled}>
	<a href="/journal/{entry.entry_date}#e-{entry.id}">
		<span class="when">{entry.start_time ? showRange(entry.start_time, entry.end_time) : 'Journée'}</span>
		<span class="what">
			<b>{title}</b>
			<small><span class="tag">{entry.cancelled ? 'annulé' : 'prévu'}</span> · {placeName(entry)}</small>
		</span>
	</a>
	<span class="tools">
	<NotesButton notes={entry.notes} what={title} create={async () => (await v2.entryNotes(entry.id)).entry_id} />
	<button
		class="bin"
		disabled={busy}
		onclick={toggle}
		title={entry.cancelled ? 'Rétablir' : 'Marquer comme annulé'}
		aria-label={entry.cancelled ? `Rétablir « ${title} »` : `Marquer « ${title} » comme annulé`}
	>
		{#if entry.cancelled}
			<span aria-hidden="true">↺</span>
		{:else}
			<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
				<path d="M2.5 4h11M6.5 4V2.5h3V4M4 4l.7 9.5h6.6L12 4M6.8 6.5v5M9.2 6.5v5" />
			</svg>
		{/if}
	</button>
	</span>
	{#if message}<small class="warn" role="alert">{message}</small>{/if}
</div>

<style>
	.planned {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		align-items: center;
		border-left: 3px solid var(--line);
		border-bottom: 1px solid var(--line);
	}
	a {
		display: grid;
		grid-template-columns: 92px minmax(0, 1fr);
		gap: 10px;
		align-items: baseline;
		padding: 8px 0 8px 12px;
		text-decoration: none;
		color: var(--ink);
	}
	a:hover b {
		text-decoration: underline;
	}
	.cancelled b,
	.cancelled .when {
		text-decoration: line-through;
		color: var(--muted);
	}
	.when {
		font-family: var(--sans);
		font-size: 0.8125rem;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
	}
	.what {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
		overflow-wrap: anywhere;
	}
	small {
		color: var(--muted);
		font-size: 0.8125rem;
	}
	.tag {
		font-size: 0.6875rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}
	.tools {
		display: inline-flex;
		align-items: center;
		gap: 2px;
	}
	.bin {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		margin-right: 4px;
		padding: 0;
		border: 0;
		border-radius: 6px;
		background: none;
		color: var(--muted);
		opacity: 0.55;
		cursor: pointer;
	}
	.planned:hover .bin,
	.bin:focus-visible {
		opacity: 1;
	}
	.bin:hover {
		background: var(--soft);
		color: var(--warn);
	}
	.cancelled .bin:hover {
		color: var(--accent);
	}
	.warn {
		grid-column: 1 / -1;
		padding: 0 0 6px 12px;
		color: var(--warn);
	}
</style>
