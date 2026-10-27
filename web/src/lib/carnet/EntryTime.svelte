<script lang="ts">
	// The time of a journal entry, in its margin: « 09:30–11:00 · 1 h 30 ». A click lets you type
	// the range as you would write it (« 9h30-11h »). With a start and an end, the time counts
	// in Ma journée (the server keeps one block in step with the entry).
	import { tick } from 'svelte';
	import { ApiError } from '../api.js';
	import { v2, type Entry } from '../api2.js';
	import { failure } from './state.svelte.js';
	import { formatMinutes, formatRange, parseRange, rangeMinutes, showRange } from './timerange.js';

	let { entry, onsaved }: { entry: Entry; onsaved: () => void } = $props();

	let editing = $state(false);
	let text = $state('');
	let error = $state('');
	let saving = $state(false);
	let input: HTMLInputElement | undefined = $state();

	let minutes = $derived(entry.cancelled ? null : rangeMinutes(entry.start_time, entry.end_time)); // cancelled: nothing counted

	async function open() {
		text = entry.start_time ? formatRange(entry.start_time, entry.end_time) + (entry.end_time ? '' : '-') : '';
		error = '';
		editing = true;
		await tick();
		input?.focus();
		input?.select();
	}

	async function save() {
		const range = parseRange(text);
		if (!range) {
			error = 'Écris par exemple 9h30-11h.';
			return;
		}
		if (range.start === entry.start_time && range.end === entry.end_time) {
			editing = false;
			return;
		}
		saving = true;
		try {
			await v2.updateEntry(entry.id, { expected_revision: entry.revision, start_time: range.start, end_time: range.end });
			editing = false;
			onsaved();
		} catch (err) {
			error = err instanceof ApiError && err.status === 409 ? 'Modifié ailleurs : recharge la page.' : failure(err, '');
		} finally {
			saving = false;
		}
	}
</script>

{#if editing}
	<form class="range" onsubmit={(e) => { e.preventDefault(); void save(); }}>
		<input
			bind:this={input}
			bind:value={text}
			placeholder="9h30-11h"
			aria-label="Plage horaire (vide pour l’enlever)"
			aria-invalid={!!error}
			disabled={saving}
			onkeydown={(e) => { if (e.key === 'Escape') { e.preventDefault(); editing = false; } }}
			onblur={() => { if (editing && !saving && !error) void save(); }}
		/>
		{#if error}<small class="err" role="alert">{error}</small>{/if}
	</form>
{:else}
	<button
		class="time"
		class:empty={!entry.start_time}
		onclick={open}
		title={minutes !== null ? 'Compté dans Ma journée · cliquer pour modifier' : 'Indiquer une plage horaire (9h30-11h) : elle comptera dans Ma journée'}
	>
		{#if entry.start_time}
			<span class="hours" class:range={!!entry.end_time}>{showRange(entry.start_time, entry.end_time)}</span>
			{#if minutes !== null}<small>{formatMinutes(minutes)}</small>{/if}
		{:else}
			<span aria-hidden="true">＋</span><span class="visually-hidden">Indiquer une plage horaire</span>
		{/if}
	</button>
{/if}

<style>
	.time {
		display: flex;
		flex-direction: column;
		align-items: flex-end;
		padding: 0;
		background: none;
		border: 0;
		font: inherit;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		color: var(--ink);
		min-height: 1.6em;
		cursor: pointer;
		text-align: right;
	}
	.hours {
		white-space: nowrap;
	}
	.hours.range {
		font-size: 0.8125rem;
	}
	.time:hover .hours {
		text-decoration: underline dotted;
	}
	.time small {
		font-weight: 400;
		font-size: 0.75rem;
		color: var(--accent);
	}
	.time.empty {
		color: var(--line);
		font-weight: 400;
	}
	.time.empty:hover,
	.time.empty:focus-visible {
		color: var(--muted);
	}
	.range {
		display: flex;
		flex-direction: column;
		align-items: flex-end;
		gap: 2px;
	}
	input {
		width: 100%;
		max-width: 92px;
		font: inherit;
		font-size: 0.8125rem;
		padding: 2px 4px;
		text-align: right;
		color: var(--ink);
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 4px;
	}
	.err {
		font-size: 0.6875rem;
		color: var(--warn);
		line-height: 1.2;
	}
</style>
