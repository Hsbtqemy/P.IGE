<script lang="ts">
	// « Prendre des notes » on something of the agenda: a small pencil that opens the long text
	// of notes (written in « Écrire »), creating it the first time.
	import { goto } from '$app/navigation';
	import type { NoteRef } from '../api2.js';
	import { failure } from './state.svelte.js';

	let { notes, create, what }: { notes: NoteRef | null | undefined; create: () => Promise<string>; what: string } = $props();
	let busy = $state(false);
	let message = $state('');

	async function open() {
		busy = true;
		message = '';
		try {
			await goto(`/ecrire/${await create()}`);
		} catch (err) {
			message = failure(err, '');
			busy = false;
		}
	}
</script>

{#if notes}
	<a class="notes has" href="/ecrire/{notes.id}" title="Notes : {notes.title}">✎ notes</a>
{:else}
	<button class="notes" disabled={busy} onclick={open} title="Prendre des notes" aria-label="Prendre des notes pour « {what} »">✎</button>
{/if}
{#if message}<small class="warn" role="alert">{message}</small>{/if}

<style>
	.notes {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 28px;
		height: 28px;
		padding: 0 4px;
		border: 0;
		border-radius: 6px;
		background: none;
		font: inherit;
		font-family: var(--sans);
		font-size: 0.875rem;
		color: var(--muted);
		text-decoration: none;
		white-space: nowrap;
		cursor: pointer;
	}
	button.notes {
		opacity: 0.6;
	}
	button.notes:hover,
	button.notes:focus-visible {
		opacity: 1;
		background: var(--soft);
		color: var(--accent);
	}
	.notes.has {
		color: var(--accent);
		font-size: 0.8125rem;
	}
	.notes.has:hover {
		text-decoration: underline;
	}
	.warn {
		color: var(--warn);
		font-size: 0.75rem;
	}
</style>
