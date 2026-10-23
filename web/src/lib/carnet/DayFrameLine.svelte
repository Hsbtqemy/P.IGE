<script lang="ts">
	// One line in the Journal about the day's frame; everything happens in Ma journée.
	import { v2, type DayFrame } from '../api2.js';
	import { hhmm } from './dayframe.js';
	import { duration, timeZone, todayIso } from './state.svelte.js';

	let { day }: { day: string } = $props();
	let frame = $state<DayFrame | null>(null);

	$effect(() => {
		const current = day;
		frame = null;
		v2.frame(current, timeZone())
			.then((f) => {
				if (current === day) frame = f;
			})
			.catch(() => {});
	});

	let open = $derived(frame?.priorities.filter((p) => !(p.task_id ? p.task_status === 'done' : p.done) && !p.carried) ?? []);
</script>

{#if frame}
	<p class="frame-line">
		{#if frame.ended_at && frame.span}
			Journée {hhmm(frame.span.start)} → {hhmm(frame.span.end)} · {duration(frame.span.seconds)}
		{:else if frame.started_at}
			Commencée à {hhmm(frame.started_at)}{#if open.length} · à faire : {open.map((p) => p.text).join(' · ')}{/if}
		{:else if day === todayIso()}
			{#if frame.from_before}À reprendre : {frame.from_before.text.split('\n')[0]} · {/if}<a href="/journee/{day}">Commencer la journée →</a>
		{/if}
		{#if frame.started_at}<a href="/journee/{day}">Ma journée →</a>{/if}
	</p>
{/if}

<style>
	.frame-line {
		margin: 0;
		font-family: var(--sans);
		font-size: 0.875rem;
		color: var(--muted);
		display: flex;
		flex-wrap: wrap;
		gap: 4px 12px;
	}
	.frame-line:empty {
		display: none;
	}
</style>
