<script lang="ts">
	import { goto, replaceState } from '$app/navigation';
	import { page } from '$app/state';
	import { v2, type AgendaEvent, type CalendarInfo } from '#lib/api2.js';
	import EventRow from '#lib/carnet/EventRow.svelte';
	import { failure, isDay, longDate, shiftDay, timeZone, todayIso } from '#lib/carnet/state.svelte.js';

	let day = $derived(isDay(page.params.day ?? '') ? (page.params.day as string) : '');
	let view = $derived<'semaine' | 'mois'>(page.url.searchParams.get('vue') === 'mois' ? 'mois' : 'semaine');

	function mondayOf(iso: string): string {
		const d = new Date(`${iso}T12:00:00`);
		return shiftDay(iso, -((d.getDay() + 6) % 7));
	}

	/** Monday of the week shown (week view). */
	let monday = $derived(day ? mondayOf(day) : '');
	/** First day of the month shown (month view), and the Monday-to-Sunday grid around it. */
	let monthStart = $derived(day ? `${day.slice(0, 8)}01` : '');
	let gridStart = $derived(monthStart ? mondayOf(monthStart) : '');
	let gridDays = $derived.by(() => {
		if (!monthStart) return 0;
		const next = new Date(`${monthStart}T12:00:00`);
		next.setMonth(next.getMonth() + 1);
		const last = shiftDay(next.toISOString().slice(0, 10), -1);
		const end = shiftDay(mondayOf(last), 7);
		return Math.round((new Date(`${end}T12:00:00`).getTime() - new Date(`${gridStart}T12:00:00`).getTime()) / 86_400_000);
	});

	let range = $derived(view === 'mois' ? { start: gridStart, days: gridDays } : { start: monday, days: 7 });
	let rangeKey = $derived(`${range.start}/${range.days}`);

	let events = $state<AgendaEvent[] | null>(null);
	let calendars = $state<CalendarInfo[]>([]);
	let message = $state('');
	let refreshing = $state(false);

	function load(start: string, days: number) {
		const key = `${start}/${days}`;
		return Promise.all([v2.agenda(start, days, timeZone()), v2.calendars()])
			.then(([e, c]) => {
				if (key !== rangeKey) return;
				events = e;
				calendars = c;
			})
			.catch((err) => (message = failure(err, 'Agenda non chargé : ')));
	}

	$effect(() => {
		const { start, days } = range;
		if (!start || !days) return;
		events = null;
		message = '';
		void load(start, days);
	});

	/** Re-read every active calendar now, instead of waiting for the next 15-minute round. */
	async function refresh() {
		refreshing = true;
		message = '';
		const results = await Promise.allSettled(calendars.filter((c) => c.active).map((c) => v2.syncCalendar(c.id)));
		const failed = results.filter((r) => r.status === 'rejected').length;
		await load(range.start, range.days);
		if (failed) message = `${failed} calendrier${failed > 1 ? 's' : ''} n’${failed > 1 ? 'ont' : 'a'} pas pu être relu${failed > 1 ? 's' : ''} : voir ci-dessous ou dans Réglages.`;
		refreshing = false;
	}

	function localIso(ms: number): string {
		return new Date(ms - new Date(ms).getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
	}

	/** Does the event take place (even partly) on this local day? */
	function onDay(e: AgendaEvent, iso: string): boolean {
		if (e.all_day) return e.start <= iso && iso < e.end;
		const first = localIso(new Date(e.start).getTime());
		const last = localIso(new Date(e.end).getTime() - 1);
		return first <= iso && iso <= last;
	}

	function listFor(iso: string): AgendaEvent[] {
		return (events ?? []).filter((e) => onDay(e, iso));
	}

	let days = $derived(
		monday && view === 'semaine' ? Array.from({ length: 7 }, (_, i) => shiftDay(monday, i)).map((iso) => ({ iso, list: listFor(iso) })) : []
	);

	let cells = $derived(
		view === 'mois' && gridStart
			? Array.from({ length: gridDays }, (_, i) => shiftDay(gridStart, i)).map((iso) => ({
					iso,
					list: listFor(iso),
					inMonth: iso.slice(0, 7) === monthStart.slice(0, 7)
				}))
			: []
	);

	function changed(updated: AgendaEvent) {
		events = (events ?? []).map((e) => (e.id === updated.id ? updated : e));
	}

	function shiftMonth(delta: number): string {
		const d = new Date(`${monthStart}T12:00:00`);
		d.setMonth(d.getMonth() + delta);
		return d.toISOString().slice(0, 10);
	}

	function href(iso: string, v = view): string {
		return v === 'mois' ? `/agenda/${iso}?vue=mois` : `/agenda/${iso}`;
	}

	/** The day opened under the month grid (a click does not reload the page). */
	let selected = $state('');
	$effect(() => {
		selected = day;
	});

	function pick(iso: string) {
		if (iso.slice(0, 7) !== monthStart.slice(0, 7)) {
			void goto(href(iso));
			return;
		}
		selected = iso;
		replaceState(href(iso), {});
	}

	const clock = (iso: string) => new Date(iso).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
	const monthName = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString('fr-FR', { month: 'long', year: 'numeric' });
	const WEEKDAYS = ['lun.', 'mar.', 'mer.', 'jeu.', 'ven.', 'sam.', 'dim.'];

	let problems = $derived(calendars.filter((c) => c.active && c.last_error));
	let today = $derived(todayIso());
</script>

<svelte:head><title>Agenda · P.IGE</title></svelte:head>

<div class="wrap">
	{#if !day}
		<p>Date invalide. <a href="/agenda/{todayIso()}">Aller à aujourd’hui</a></p>
	{:else}
		<header>
			<div class="bar">
				<div class="views" role="group" aria-label="Vue">
					<a href={href(day, 'semaine')} aria-current={view === 'semaine' ? 'page' : undefined}>Semaine</a>
					<a href={href(day, 'mois')} aria-current={view === 'mois' ? 'page' : undefined}>Mois</a>
				</div>
				<div class="nav">
					{#if view === 'mois'}
						<a href={href(shiftMonth(-1))}>‹ Mois précédent</a>
						{#if today.slice(0, 7) !== monthStart.slice(0, 7)}<a href={href(today)}>Ce mois-ci</a>{/if}
						<a href={href(shiftMonth(1))}>Mois suivant ›</a>
					{:else}
						<a href={href(shiftDay(monday, -7))}>‹ Semaine précédente</a>
						{#if !(today >= monday && today < shiftDay(monday, 7))}<a href={href(today)}>Cette semaine</a>{/if}
						<a href={href(shiftDay(monday, 7))}>Semaine suivante ›</a>
					{/if}
				</div>
				{#if calendars.some((c) => c.active)}
					<button class="refresh" onclick={refresh} disabled={refreshing}>{refreshing ? 'Lecture…' : '↻ Actualiser'}</button>
				{/if}
			</div>
			{#if view === 'mois'}
				<h1>Agenda <span class="range">{monthName(monthStart)}</span></h1>
			{:else}
				<h1>Agenda <span class="range">du {longDate(monday).toLocaleLowerCase('fr')} au {longDate(shiftDay(monday, 6)).toLocaleLowerCase('fr')}</span></h1>
			{/if}
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
		{:else if view === 'mois'}
			<div class="month" role="grid" aria-label="Mois de {monthName(monthStart)}">
				<div class="weekdays" role="row">
					{#each WEEKDAYS as w (w)}<span role="columnheader">{w}</span>{/each}
				</div>
				<div class="cells">
					{#each cells as c (c.iso)}
						<button
							class="cell"
							class:out={!c.inMonth}
							class:today={c.iso === today}
							class:selected={c.iso === selected}
							role="gridcell"
							aria-selected={c.iso === selected}
							aria-label="{longDate(c.iso)}, {c.list.length} événement{c.list.length > 1 ? 's' : ''}"
							onclick={() => pick(c.iso)}
						>
							<span class="num">{Number(c.iso.slice(8))}</span>
							{#each c.list.slice(0, 3) as e (e.id)}
								<span class="chip" class:gone={e.status === 'cancelled' || e.status === 'removed'} style="--cal: {e.color || 'var(--decision)'}">
									{#if !e.all_day}<b>{clock(e.start)}</b>{/if}
									{e.title}
								</span>
							{/each}
							{#if c.list.length > 3}<span class="more">+{c.list.length - 3}</span>{/if}
							{#if c.list.length}<span class="dots" aria-hidden="true">{#each c.list.slice(0, 4) as e (e.id)}<i style="background: {e.color || 'var(--decision)'}"></i>{/each}</span>{/if}
						</button>
					{/each}
				</div>
			</div>
			<section class="dayview" aria-label={longDate(selected || day)}>
				<h2><a href="/journal/{selected || day}">{longDate(selected || day)}</a> <small>{listFor(selected || day).length || ''}</small></h2>
				{#each listFor(selected || day) as e (e.id)}
					<EventRow event={e} choosePlace onchanged={changed} onreload={() => load(range.start, range.days)} />
				{:else}
					<p class="muted">Rien ce jour-là.</p>
				{/each}
			</section>
		{:else}
			{#each days as d (d.iso)}
				<section class:today={d.iso === today} aria-label={longDate(d.iso)}>
					<h2><a href="/journal/{d.iso}">{longDate(d.iso)}</a> <small>{d.list.length || ''}</small></h2>
					{#each d.list as e (e.id)}
						<EventRow event={e} choosePlace onchanged={changed} onreload={() => load(range.start, range.days)} />
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
	.bar {
		display: flex;
		flex-wrap: wrap;
		gap: 10px 18px;
		align-items: center;
	}
	.views {
		display: inline-flex;
		border: 1px solid var(--line);
		border-radius: 16px;
		overflow: hidden;
	}
	.views a {
		padding: 3px 12px;
		font-size: 0.8125rem;
		text-decoration: none;
		color: var(--muted);
	}
	.views a[aria-current='page'] {
		font-weight: 700;
		color: var(--ink);
		background: var(--soft);
	}
	.nav {
		display: flex;
		flex-wrap: wrap;
		gap: 14px;
		font-size: 0.875rem;
	}
	.month {
		border: 1px solid var(--line);
		border-radius: 10px;
		overflow: hidden;
		background: var(--surface);
	}
	.weekdays,
	.cells {
		display: grid;
		grid-template-columns: repeat(7, minmax(0, 1fr));
	}
	.weekdays span {
		padding: 6px 8px;
		font-size: 0.75rem;
		font-weight: 700;
		color: var(--muted);
		text-transform: uppercase;
		border-bottom: 1px solid var(--line);
	}
	.cell {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-height: 104px;
		min-width: 0;
		padding: 4px 5px 6px;
		font: inherit;
		text-align: left;
		color: var(--ink);
		background: transparent;
		border: 0;
		border-right: 1px solid var(--line);
		border-bottom: 1px solid var(--line);
		cursor: pointer;
	}
	.cell:nth-child(7n) {
		border-right: 0;
	}
	.cell:hover {
		background: var(--softer);
	}
	.cell.out {
		color: var(--muted);
		background: var(--bg);
	}
	.cell.selected {
		box-shadow: inset 0 0 0 2px var(--accent);
	}
	.num {
		font-size: 0.8125rem;
		font-weight: 700;
	}
	.cell.today .num {
		display: inline-grid;
		place-items: center;
		width: 22px;
		height: 22px;
		color: var(--accent-ink);
		background: var(--accent);
		border-radius: 50%;
	}
	.chip {
		display: block;
		padding: 1px 4px;
		font-size: 0.75rem;
		line-height: 1.3;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		border-left: 3px solid var(--cal);
		background: var(--softer);
		border-radius: 3px;
	}
	.chip b {
		font-weight: 700;
		font-variant-numeric: tabular-nums;
	}
	.chip.gone {
		opacity: 0.5;
		text-decoration: line-through;
	}
	.more {
		font-size: 0.75rem;
		color: var(--muted);
	}
	.dots {
		display: none;
	}
	.dayview {
		margin-top: 4px;
	}
	@media (max-width: 760px) {
		.cell {
			min-height: 54px;
			align-items: center;
		}
		.chip,
		.more {
			display: none;
		}
		.dots {
			display: flex;
			gap: 3px;
		}
		.dots i {
			width: 6px;
			height: 6px;
			border-radius: 50%;
		}
	}
	.nav a {
		color: var(--muted);
	}
	.refresh {
		padding: 2px 10px;
		font: inherit;
		color: var(--ink);
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 14px;
		cursor: pointer;
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
