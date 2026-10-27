<script lang="ts">
	import { v2, type AgendaEvent, type Target } from '../api2.js';
	import { carnet, failure, placeName, timeZone } from './state.svelte.js';
	import NotesButton from './NotesButton.svelte';

	let {
		event,
		choosePlace = false,
		onchanged,
		onreload
	}: {
		event: AgendaEvent;
		choosePlace?: boolean;
		onchanged?: (e: AgendaEvent) => void;
		/** After filing a whole series: the other occurrences shown changed too. */
		onreload?: () => void;
	} = $props();

	// The select shows where the meeting is filed (its note or time, else the place chosen for
	// it or its series) and changing it files it there right away; « Noter » and « Compter » use it.
	const placeKey = (p: AgendaEvent['place']) => (p ? (p.project_id ? `p:${p.project_id}` : `s:${p.space_id}`) : '');
	let place = $state('');
	let placedKey = $derived(placeKey(event.place));
	$effect(() => {
		place = placedKey;
	});
	let filed = $derived(!!(event.entry_id || event.block_id));
	let busy = $state(false);
	let message = $state('');

	const clock = (iso: string) => new Date(iso).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
	let hours = $derived(event.all_day ? 'Journée' : `${clock(event.start)}–${clock(event.end)}`);
	let gone = $derived(event.status === 'cancelled' || event.status === 'removed');

	function target(): Target {
		if (place.startsWith('p:')) return { project_id: place.slice(2) };
		if (place.startsWith('s:')) return { space_id: place.slice(2) };
		return {};
	}

	/** Where a note or time will go when no place is chosen. */
	let defaultPlace = $derived(event.project_id ? placeName({ project_id: event.project_id, space_id: '' }) : 'À trier');

	async function note() {
		busy = true;
		message = '';
		try {
			const r = await v2.noteEvent(event.id, target(), timeZone());
			onchanged?.(r.event);
		} catch (err) {
			message = failure(err, 'Note non créée : ');
		} finally {
			busy = false;
		}
	}

	async function count() {
		busy = true;
		message = '';
		try {
			const r = await v2.countEvent(event.id, target());
			onchanged?.(r.event);
		} catch (err) {
			message = failure(err, 'Temps non compté : ');
		} finally {
			busy = false;
		}
	}

	let asking = $state(false); // a recurring event: this occurrence or the whole series?

	function choose() {
		if (place === placedKey) return;
		if (event.recurring) asking = true;
		else void apply(false);
	}

	async function apply(series: boolean) {
		asking = false;
		busy = true;
		message = '';
		try {
			onchanged?.(await v2.placeEvent(event.id, target(), series));
			if (series) onreload?.();
		} catch (err) {
			message = failure(err, 'Réunion non rangée : ');
			place = placedKey;
		} finally {
			busy = false;
		}
	}

	function cancelChoice() {
		asking = false;
		place = placedKey;
	}

	function localDay(): string {
		if (event.all_day) return event.start;
		const d = new Date(event.start);
		return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
	}
</script>

<div class="event" class:gone style="--cal: {event.color || 'var(--decision)'}">
	<span class="hours">{hours}</span>
	<span class="what">
		<b>{event.title}</b>
		<small>
			{event.calendar}{#if event.location} · {event.location}{/if}{#if event.attendees.length} · {event.attendees.length} participant{event.attendees.length > 1 ? 's' : ''}{/if}
			{#if event.status === 'cancelled'} · annulé{/if}{#if event.status === 'removed'} · retiré du calendrier{/if}
		</small>
		{#if event.place_source === 'series' || (event.series_filed && event.place_source === 'filed')}<small class="series">↻ rangé avec toute la série</small>{/if}
		{#if asking}
			<span class="ask" role="group" aria-label="Ranger quelles occurrences ?">
				<small>Ranger :</small>
				<button class="btn" onclick={() => apply(false)}>Cette fois</button>
				<button class="btn primary" onclick={() => apply(true)}>Toute la série</button>
				<button class="plain cancel" onclick={cancelChoice} aria-label="Annuler">×</button>
			</span>
		{/if}
		{#if message}<small class="warn">{message}</small>{/if}
	</span>
	<span class="actions">
		{#if choosePlace}
			<select
				bind:value={place}
				onchange={choose}
				disabled={busy}
				aria-label="Ranger dans"
				title={filed ? 'Ranger la note et le temps ailleurs' : 'Où ranger la note et le temps'}
			>
				{#if !filed}<option value="">{event.place ? `Par défaut (${defaultPlace})` : defaultPlace}</option>{/if}
				{#each carnet.tree?.spaces ?? [] as s (s.id)}
					<optgroup label={s.name}>
						<option value="s:{s.id}">{s.name} (sans projet)</option>
						{#each s.projects as p (p.id)}<option value="p:{p.id}">{p.name}</option>{/each}
					</optgroup>
				{/each}
			</select>
		{/if}
		{#if !gone || event.notes}
			<NotesButton notes={event.notes} what={event.title} create={async () => (await v2.eventNotes(event.id, target(), timeZone())).entry_id} />
		{/if}
		{#if event.entry_id && event.notes?.id === event.entry_id}
			<!-- the notes are the event's note: nothing more to show -->
		{:else if event.entry_id}
			<a class="done" href="/journal/{localDay()}">✓ noté</a>
		{:else if !gone}
			<button class="btn" disabled={busy} onclick={note} title="Créer la note de réunion dans le journal">Noter</button>
		{/if}
		{#if !event.all_day}
			{#if event.block_id}
				<span class="done">✓ compté</span>
			{:else if !gone}
				<button class="btn" disabled={busy} onclick={count} title="Compter ce temps dans Ma journée">Compter</button>
			{/if}
		{/if}
	</span>
</div>

<style>
	.event {
		display: grid;
		grid-template-columns: 96px minmax(0, 1fr) auto;
		gap: 10px;
		align-items: center;
		padding: 7px 0 7px 10px;
		border-left: 3px solid var(--cal);
		border-bottom: 1px solid var(--line);
	}
	.gone {
		opacity: 0.55;
	}
	.gone b {
		text-decoration: line-through;
	}
	.hours {
		font-size: 0.875rem;
		font-variant-numeric: tabular-nums;
		color: var(--muted);
	}
	.what {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}
	.what b {
		overflow-wrap: anywhere;
	}
	small {
		font-size: 0.8125rem;
		color: var(--muted);
	}
	.warn {
		color: var(--warn);
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		align-items: center;
		justify-content: flex-end;
	}
	.actions .btn {
		min-height: 30px;
		padding: 0 10px;
	}
	select {
		max-width: 150px;
		font: inherit;
		font-size: 0.8125rem;
		color: var(--ink);
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 6px;
		padding: 3px 4px;
	}
	.done {
		font-size: 0.8125rem;
		font-weight: 700;
		color: var(--accent);
		text-decoration: none;
	}
	@media (max-width: 600px) {
		.event {
			grid-template-columns: 76px minmax(0, 1fr);
		}
		.actions {
			grid-column: 2;
			justify-content: flex-start;
		}
	}
	.series {
		color: var(--muted);
	}
	.ask {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px;
		margin-top: 4px;
	}
	.cancel {
		background: none;
		border: 0;
		color: var(--muted);
		font-size: 1rem;
		cursor: pointer;
	}
</style>
