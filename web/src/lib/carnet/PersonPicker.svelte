<script lang="ts">
	// Type a name: an existing person of the directory is suggested; a new name creates the person.
	import { v2, type Person } from '../api2.js';
	import { carnet, failure } from './state.svelte.js';

	let {
		onpick,
		exclude = [],
		placeholder = '+ Personne',
		id = 'person-picker'
	}: { onpick: (person: Person) => void | Promise<void>; exclude?: string[]; placeholder?: string; id?: string } = $props();

	let name = $state('');
	let busy = $state(false);
	let message = $state('');
	let choices = $derived(carnet.people.filter((p) => !exclude.includes(p.id)));

	async function submit(event: SubmitEvent) {
		event.preventDefault();
		const typed = name.trim();
		if (!typed) return;
		busy = true;
		message = '';
		try {
			const key = typed.toLocaleLowerCase('fr');
			let person = carnet.people.find((p) => p.display_name.toLocaleLowerCase('fr') === key);
			if (!person) {
				person = await v2.person(typed);
				const created = person;
				if (!carnet.people.some((p) => p.id === created.id)) carnet.people = [...carnet.people, created];
			}
			await onpick(person);
			name = '';
		} catch (err) {
			message = failure(err, 'Personne non ajoutée : ');
		} finally {
			busy = false;
		}
	}
</script>

<form class="picker" onsubmit={submit}>
	<input {id} bind:value={name} list="{id}-list" {placeholder} aria-label={placeholder} autocomplete="off" disabled={busy} />
	<datalist id="{id}-list">
		{#each choices as p (p.id)}<option value={p.display_name}>{p.organisation ?? p.email ?? ''}</option>{/each}
	</datalist>
	{#if message}<small class="warn">{message}</small>{/if}
</form>

<style>
	.picker {
		display: flex;
		flex-direction: column;
		gap: 4px;
		min-width: 0;
	}
	input {
		font: inherit;
		font-size: 0.875rem;
		color: var(--ink);
		background: var(--surface);
		border: 1px dashed var(--line);
		border-radius: 6px;
		padding: 5px 8px;
		min-width: 0;
		width: 100%;
		max-width: 220px;
		min-width: 9em;
	}
	.warn {
		color: var(--warn);
		font-size: 0.8125rem;
	}
</style>
