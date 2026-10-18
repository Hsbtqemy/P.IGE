<script lang="ts">
	import type { Entry } from '../api2.js';
	import { placeName } from './state.svelte.js';

	let { entries, showPlace = false, empty = 'Rien d’écrit.' }: { entries: Entry[]; showPlace?: boolean; empty?: string } =
		$props();

	function shortDate(iso: string): { day: string; month: string; year: string } {
		const d = new Date(`${iso}T12:00:00`);
		return {
			day: String(d.getDate()),
			month: d.toLocaleDateString('fr-FR', { month: 'short' }),
			year: d.getFullYear() === new Date().getFullYear() ? '' : String(d.getFullYear())
		};
	}
</script>

{#each entries as entry (entry.id)}
	{@const d = shortDate(entry.entry_date)}
	{@const line = [showPlace ? placeName(entry) : '', entry.people.map((p) => p.display_name).join(', ')].filter(Boolean).join(' · ')}
	<a class="entry" href={entry.source === 'writing' ? `/ecrire/${entry.id}` : `/journal/${entry.entry_date}`}>
		<span class="date"><b>{d.day}</b><small>{d.month} {d.year}</small></span>
		<span class="text">
			<b>{entry.title || entry.body.slice(0, 80)}</b>
			{#if line}<small>{line}</small>{/if}
		</span>
	</a>
{:else}
	<p class="muted">{empty}</p>
{/each}

<style>
	.entry {
		display: grid;
		grid-template-columns: 48px minmax(0, 1fr);
		gap: 12px;
		padding: 8px 0;
		border-bottom: 1px solid var(--line);
		text-decoration: none;
	}
	.date {
		display: flex;
		flex-direction: column;
		padding-right: 8px;
		border-right: var(--margin);
		line-height: 1.15;
	}
	.text {
		display: flex;
		flex-direction: column;
		font-family: var(--serif);
	}
	small,
	.muted {
		font-family: var(--sans);
		font-size: 0.875rem;
		color: var(--muted);
	}
</style>
