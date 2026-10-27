<script lang="ts">
	// Something written ahead in the journal for this day (a training, leave, a meeting not in
	// any calendar): shown with the agenda, opened in the journal.
	import type { Entry } from '../api2.js';
	import { placeName } from './state.svelte.js';
	import { showRange } from './timerange.js';

	let { entry }: { entry: Entry } = $props();
	let title = $derived(entry.title || entry.body.split('\n').find((l) => l.trim())?.trim().slice(0, 120) || 'Sans titre');
</script>

<a class="planned" href="/journal/{entry.entry_date}#e-{entry.id}">
	<span class="when">{entry.start_time ? showRange(entry.start_time, entry.end_time) : 'Journée'}</span>
	<span class="what">
		<b>{title}</b>
		<small><span class="tag">prévu</span> · {placeName(entry)}</small>
	</span>
</a>

<style>
	.planned {
		display: grid;
		grid-template-columns: 92px minmax(0, 1fr);
		gap: 10px;
		align-items: baseline;
		padding: 8px 0 8px 12px;
		border-left: 3px solid var(--line);
		border-bottom: 1px solid var(--line);
		text-decoration: none;
		color: var(--ink);
	}
	.planned:hover b {
		text-decoration: underline;
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
</style>
