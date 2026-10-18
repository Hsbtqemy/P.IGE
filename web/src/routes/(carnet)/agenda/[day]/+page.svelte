<script lang="ts">
	import { page } from '$app/state';
	import { v2, type AgendaEvent, type CalendarInfo } from '#lib/api2.js';
	import EventRow from '#lib/carnet/EventRow.svelte';
	import { failure, isDay, longDate, shiftDay, timeZone, todayIso } from '#lib/carnet/state.svelte.js';

	let day = $derived(isDay(page.params.day ?? '') ? (page.params.day as string) : '');
	/** Monday of the week shown. */
	let monday = $derived.by(() => {
		if (!day) return '';
		const d = new Date(`${day}T12:00:00`);
		return shiftDay(day, -((d.getDay() + 6) % 7));
	});
	let events = $state<AgendaEvent[] | null>(null);
	let calendars = $state<CalendarInfo[]>([]);
	let message = $state('');

	$effect(() => {
		const start = monday;
		if (!start) return;
		events = null;
		message = '';
		Promise.all([v2.agenda(start, 7, timeZone()), v2.calendars()])
			.then(([e, c]) => {
				if (start !== monday) return;
				events = e;
				calendars = c;
			})
			.catch((err) => (message = failure(err, 'Agenda non chargé : ')));
	});

	function localDay(e: AgendaEvent): string {
		if (e.all_day) return e.start;
		const d = new Date(e.start);
		return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
	}

	let days = $derived(
		monday
			? Array.from({ length: 7 }, (_, i) => {
					const iso = shiftDay(monday, i);
					const list = (events ?? []).filter((e) =>
						e.all_day ? e.start <= iso && iso < e.end : localDay(e) === iso
					);
					return { iso, list };
				})
			: []
	);

	function changed(updated: AgendaEvent) {
		events = (events ?? []).map((e) => (e.id === updated.id ? updated : e));
	}

	let problems = $derived(calendars.filter((c) => c.active && c.last_error));
</script>

<svelte:head><title>Agenda · P.IGE</title></svelte:head>

<div class="wrap">
	{#if !day}
		<p>Date invalide. <a href="/agenda/{todayIso()}">Aller à aujourd’hui</a></p>
	{:else}
		<header>
			<div class="nav">
				<a href="/agenda/{shiftDay(monday, -7)}">‹ Semaine précédente</a>
				{#if !(todayIso() >= monday && todayIso() < shiftDay(monday, 7))}<a href="/agenda/{todayIso()}">Cette semaine</a>{/if}
				<a href="/agenda/{shiftDay(monday, 7)}">Semaine suivante ›</a>
			</div>
			<h1>Agenda <span class="range">du {longDate(monday).toLocaleLowerCase('fr')} au {longDate(shiftDay(monday, 6)).toLocaleLowerCase('fr')}</span></h1>
		</header>

		{#if message}<p class="message" role="alert">{message}</p>{/if}
		{#each problems as c (c.id)}
			<p class="message" role="alert">« {c.name} » : {c.last_error} <a href="/reglages">Réglages</a></p>
		{/each}

		{#if events && !calendars.length}
			<p class="empty">
				Aucun calendrier suivi. Ajoute l’adresse de ton agenda (ICS) dans <a href="/reglages">Réglages › Calendriers</a> : les
				réunions apparaîtront ici, dans le journal et dans Ma journée.
			</p>
		{:else if !events}
			<p class="muted">Chargement…</p>
		{:else}
			{#each days as d (d.iso)}
				<section class:today={d.iso === todayIso()} aria-label={longDate(d.iso)}>
					<h2><a href="/journal/{d.iso}">{longDate(d.iso)}</a> <small>{d.list.length || ''}</small></h2>
					{#each d.list as e (e.id)}
						<EventRow event={e} choosePlace onchanged={changed} />
					{:else}
						<p class="muted">—</p>
					{/each}
				</section>
			{/each}
		{/if}
	{/if}
</div>

<style>
	.wrap {
		padding: 22px 32px 48px;
		display: flex;
		flex-direction: column;
		gap: 16px;
		max-width: 920px;
	}
	.nav {
		display: flex;
		flex-wrap: wrap;
		gap: 14px;
		font-size: 0.875rem;
	}
	.nav a {
		color: var(--muted);
	}
	h1 {
		font-size: 1.875rem;
		margin: 4px 0 0;
	}
	.range {
		font-weight: 400;
		font-style: italic;
		font-size: 1.125rem;
		color: var(--muted);
	}
	h2 {
		margin: 0 0 2px;
		padding-bottom: 4px;
		font-size: 1.0625rem;
		border-bottom: var(--rule);
	}
	h2 a {
		text-decoration: none;
	}
	h2 a:hover {
		text-decoration: underline;
	}
	h2 small,
	.muted {
		font-family: var(--sans);
		font-weight: 400;
		font-size: 0.875rem;
		color: var(--muted);
	}
	section.today h2 {
		color: var(--accent);
	}
	.message {
		margin: 0;
		padding: 8px 12px;
		color: var(--warn);
		background: var(--warn-soft);
		border-radius: 8px;
	}
	.empty {
		margin: 0;
		padding: 14px 16px;
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 10px;
		max-width: 64ch;
	}
	.muted {
		margin: 4px 0;
	}
	@media (max-width: 600px) {
		.wrap {
			padding: 16px;
		}
	}
</style>
