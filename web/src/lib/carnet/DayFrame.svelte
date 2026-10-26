<script lang="ts">
	// The frame of a day, all optional: « Commencer la journée » (the time, two or three
	// priorities, what was left for today), « Clore la journée » (the end, the holes in the
	// counted time, what to pick up tomorrow). Nothing declared: the day's activity gives an
	// estimate, so a forgotten click still shows how long the day was.
	import { v2, type DayFrame, type DayReport, type Priority, type Task } from '../api2.js';
	import { atClock, gaps, hhmm } from './dayframe.js';
	import { duration, failure, longDate, shiftDay, timeZone, todayIso } from './state.svelte.js';

	let {
		day,
		tasks,
		report,
		onfillgap,
		onchanged,
		refreshKey = 0
	}: {
		day: string;
		tasks: Task[];
		report: DayReport | null;
		onfillgap: (start: string, end: string) => void;
		onchanged: () => void;
		refreshKey?: number; // changed elsewhere (a priority reopened in « Fait aujourd’hui »)
	} = $props();

	let frame = $state<DayFrame | null>(null);
	let message = $state('');
	let busy = $state(false);
	let closing = $state(false);
	let editStart = $state(false);
	let startClock = $state('');
	let endClock = $state('');
	let tomorrowDraft = $state('');
	let prioDraft = $state('');
	let now = $state(Date.now());

	$effect(() => {
		const id = setInterval(() => (now = Date.now()), 60_000);
		return () => clearInterval(id);
	});

	$effect(() => {
		const current = day;
		frame = null;
		closing = false;
		editStart = false;
		message = '';
		v2.frame(current, timeZone())
			.then((f) => {
				if (current === day) frame = f;
			})
			.catch((err) => {
				if (current === day) message = failure(err, 'Cadre de la journée non chargé : ');
			});
	});

	// Refetch quietly when told something changed elsewhere; what is being edited stays open.
	let seenKey: number | null = null;
	$effect(() => {
		const key = refreshKey;
		const current = day;
		if (seenKey === null || key === seenKey) {
			seenKey = key;
			return;
		}
		seenKey = key;
		v2.frame(current, timeZone())
			.then((f) => {
				if (current === day && !busy) frame = f;
			})
			.catch(() => {});
	});

	let isToday = $derived(day === todayIso());
	let phase = $derived(!frame ? 'loading' : frame.ended_at ? 'closed' : frame.started_at ? 'started' : 'none');
	let span = $derived(frame?.span ?? null);
	let counted = $derived(report?.presence_seconds ?? 0);

	// While closing: the times typed, their holes.
	let closeStart = $derived(startClock ? atClock(day, startClock) : null);
	let closeEnd = $derived(endClock && closeStart ? atClock(day, endClock, closeStart) : null);
	let closeSeconds = $derived(closeStart && closeEnd ? (new Date(closeEnd).getTime() - new Date(closeStart).getTime()) / 1000 : null);
	let holes = $derived.by(() => {
		const from = closing ? closeStart : span?.start;
		const to = closing ? closeEnd : span?.end;
		if (!from || !to || !report) return [];
		return gaps(from, to, report.blocks.filter((b) => !b.running).map((b) => ({ start: b.start, end: b.end })));
	});

	const plain = (p: Priority) => ({ text: p.text, task_id: p.task_id, done: p.done, carried: p.carried ?? false });
	const isDone = (p: Priority) => (p.task_id ? p.task_status === 'done' : p.done);

	async function save(patch: Parameters<typeof v2.updateFrame>[2], what = 'Non enregistré') {
		busy = true;
		message = '';
		try {
			frame = await v2.updateFrame(day, timeZone(), patch);
			return true;
		} catch (err) {
			message = failure(err, `${what} : `);
			return false;
		} finally {
			busy = false;
		}
	}

	async function begin(clock?: string) {
		const at = clock ? atClock(day, clock) : new Date().toISOString();
		if (await save({ started_at: at }, 'Journée non commencée')) editStart = false;
	}

	function openStartEdit() {
		startClock = frame?.started_at ? hhmm(frame.started_at) : hhmm(new Date().toISOString());
		editStart = true;
	}

	function openClosing() {
		if (!frame) return;
		startClock = frame.started_at ? hhmm(frame.started_at) : span ? hhmm(span.start) : '09:00';
		endClock = frame.ended_at
			? hhmm(frame.ended_at)
			: isToday
				? hhmm(new Date().toISOString())
				: span
					? hhmm(span.end)
					: '18:00';
		tomorrowDraft = frame.tomorrow;
		closing = true;
	}

	async function close(event: SubmitEvent) {
		event.preventDefault();
		if (!closeStart || !closeEnd) return;
		if (await save({ started_at: closeStart, ended_at: closeEnd, tomorrow: tomorrowDraft }, 'Journée non close')) closing = false;
	}

	async function reopen() {
		if (await save({ ended_at: null }, 'Non rouverte')) closing = false;
	}

	async function addPriority(event: SubmitEvent) {
		event.preventDefault();
		const text = prioDraft.trim();
		if (!text || !frame) return;
		const task = tasks.find((t) => t.title.trim().toLowerCase() === text.toLowerCase());
		const item = { text: task ? task.title : text, task_id: task?.id ?? null, done: false };
		if (await save({ priorities: [...frame.priorities.map(plain), item] }, 'Priorité non ajoutée')) prioDraft = '';
	}

	async function removePriority(i: number) {
		if (!frame) return;
		await save({ priorities: frame.priorities.filter((_, j) => j !== i).map(plain) });
	}

	async function toggle(i: number) {
		if (!frame) return;
		const p = frame.priorities[i];
		if (p.task_id && p.task_status !== 'deleted') {
			busy = true;
			try {
				await v2.updateTask(p.task_id, { status: isDone(p) ? 'open' : 'done' });
				frame = await v2.frame(day, timeZone());
				onchanged();
			} catch (err) {
				message = failure(err, 'Tâche non modifiée : ');
			} finally {
				busy = false;
			}
			return;
		}
		if (await save({ priorities: frame.priorities.map((x, j) => (j === i ? { ...plain(x), done: !x.done } : plain(x))) })) onchanged();
	}

	/** Put an unfinished priority on tomorrow's list; it stays here, marked « → demain ». */
	async function carry(i: number) {
		if (!frame) return;
		const p = frame.priorities[i];
		const next = shiftDay(day, 1);
		busy = true;
		message = '';
		try {
			const f = await v2.frame(next, timeZone());
			if (!f.priorities.some((x) => x.text === p.text && x.task_id === p.task_id)) {
				await v2.updateFrame(next, timeZone(), { priorities: [...f.priorities.map(plain), { text: p.text, task_id: p.task_id, done: false }] });
			}
			frame = await v2.updateFrame(day, timeZone(), {
				priorities: frame.priorities.map((x, j) => (j === i ? { ...plain(x), carried: true } : plain(x)))
			});
		} catch (err) {
			message = failure(err, 'Non reporté : ');
		} finally {
			busy = false;
		}
	}

	function since(iso: string): string {
		return duration(Math.max(0, (now - new Date(iso).getTime()) / 1000));
	}
</script>

{#snippet priorities(closingView: boolean)}
	{#if frame && (frame.priorities.length || phase !== 'closed' || closingView)}
		<div class="prios">
			<span class="label">Priorités</span>
			{#if frame.priorities.length}
				<ul>
					{#each frame.priorities as p, i (i)}
						<li class:done={isDone(p)} class:carried={p.carried && !isDone(p)}>
							<input type="checkbox" checked={isDone(p)} disabled={busy || p.task_status === 'deleted'} onchange={() => toggle(i)}
								aria-label={isDone(p) ? `Rouvrir « ${p.text} »` : `Fait : « ${p.text} »`} />
							<span class="text">{p.text}{#if p.task_id}<small>{' · tâche'}</small>{/if}</span>
							{#if p.carried && !isDone(p)}
								<small class="moved">→ demain</small>
							{:else if closingView && !isDone(p)}
								<button class="plain link" disabled={busy} onclick={() => carry(i)}>→ demain</button>
							{/if}
							<button class="x" disabled={busy} onclick={() => removePriority(i)} aria-label="Enlever cette priorité" title="Enlever">×</button>
						</li>
					{/each}
				</ul>
			{/if}
			{#if frame.priorities.length < 5 && phase !== 'closed'}
				<form class="add" onsubmit={addPriority}>
					<input bind:value={prioDraft} list="frame-tasks-{day}" placeholder={frame.priorities.length ? 'Une autre…' : 'Deux ou trois choses pour aujourd’hui (tâche ou texte)'}
						aria-label="Ajouter une priorité" />
					<datalist id="frame-tasks-{day}">
						{#each tasks as t (t.id)}<option value={t.title}></option>{/each}
					</datalist>
					<button class="btn" disabled={busy || !prioDraft.trim()}>Ajouter</button>
				</form>
			{/if}
		</div>
	{/if}
{/snippet}

{#if frame}
	<section class="frame" aria-label="Cadre de la journée">
		{#if message}<p class="warn" role="alert">{message}</p>{/if}

		{#if closing}
			<form class="closing" onsubmit={close}>
				<h3>{phase === 'closed' ? 'Modifier la journée' : 'Clore la journée'}</h3>
				<div class="times">
					<label>De <input type="time" bind:value={startClock} required /></label>
					<label>à <input type="time" bind:value={endClock} required /></label>
					{#if closeSeconds}
						<span class="sum">
							<b>{duration(closeSeconds)}</b>{' · '}{duration(counted)} comptées
						</span>
					{/if}
				</div>
				{#if holes.length}
					<p class="holes-title">Moments sans temps compté <small>(une pause, tu l’ignores ; un oubli, tu peux l’attribuer)</small></p>
					<ul class="holes" aria-label="Moments sans temps compté">
						{#each holes as h (h.start)}
							<li>
								<span>{hhmm(h.start)}–{hhmm(h.end)} · {duration(h.minutes * 60)}</span>
								<button type="button" class="plain link" onclick={() => onfillgap(hhmm(h.start), hhmm(h.end))}>Attribuer</button>
							</li>
						{/each}
					</ul>
				{/if}
				{@render priorities(true)}
				<label class="tomorrow">À reprendre demain
					<textarea bind:value={tomorrowDraft} rows="2" placeholder="Où tu t’es arrêté, ce qui attend…"></textarea>
				</label>
				<div class="row">
					<button class="btn primary" disabled={busy}>{phase === 'closed' ? 'Enregistrer' : 'Clore la journée'}</button>
					<button type="button" class="btn" onclick={() => (closing = false)}>Annuler</button>
					{#if phase === 'closed'}<button type="button" class="plain link" onclick={reopen}>Rouvrir la journée</button>{/if}
				</div>
			</form>
		{:else if phase === 'none'}
			{#if day > todayIso()}
				<div class="head"><h3>À venir</h3></div>
				{#if frame.from_before}
					<p class="carry"><span class="label">À reprendre</span> <small>(noté le {longDate(frame.from_before.day).toLocaleLowerCase('fr')})</small><br />{frame.from_before.text}</p>
				{/if}
				{@render priorities(false)}
			{:else if isToday}
				<div class="head">
					<h3>Début de journée</h3>
					{#if span}<small>Activité depuis {hhmm(span.start)}</small>{/if}
				</div>
				{#if frame.from_before}
					<p class="carry"><span class="label">À reprendre</span> <small>(noté le {longDate(frame.from_before.day).toLocaleLowerCase('fr')})</small><br />{frame.from_before.text}</p>
				{/if}
				{@render priorities(false)}
				<div class="row">
					<button class="btn primary" disabled={busy} onclick={() => begin()}>Commencer la journée</button>
					{#if editStart}
						<form class="inline" onsubmit={(e) => { e.preventDefault(); void begin(startClock); }}>
							<label>commencée à <input type="time" bind:value={startClock} required /></label>
							<button class="btn" disabled={busy}>OK</button>
						</form>
					{:else}
						<button class="plain link" onclick={openStartEdit}>commencée plus tôt ?</button>
					{/if}
				</div>
			{:else}
				<div class="head">
					<p class="line">
						{#if span}
							Journée ≈ <b>{hhmm(span.start)} → {hhmm(span.end)}</b> · <span>{duration(span.seconds)}</span>
							<small>d’après ton activité</small>
						{:else}
							<span class="muted">Pas d’heures pour ce jour.</span>
						{/if}
					</p>
					<button class="plain link" onclick={openClosing}>Indiquer les heures</button>
				</div>
				{#if frame.priorities.length}{@render priorities(false)}{/if}
			{/if}
		{:else if phase === 'started'}
			<div class="head">
				<div class="line">
					Commencée à
					{#if editStart}
						<form class="inline" onsubmit={(e) => { e.preventDefault(); void begin(startClock); }}>
							<input type="time" bind:value={startClock} required aria-label="Heure de début" />
							<button class="btn" disabled={busy}>OK</button>
							<button type="button" class="plain link" onclick={() => (editStart = false)}>annuler</button>
						</form>
					{:else}
						<button class="clock" onclick={openStartEdit} title="Corriger l’heure">{hhmm(frame.started_at ?? '')}</button>
					{/if}
					{#if isToday && frame.started_at}<small>· depuis {since(frame.started_at)}</small>{:else if span}<small>· fin non indiquée (activité jusqu’à {hhmm(span.end)})</small>{/if}
				</div>
				<button class="btn primary" onclick={openClosing}>Clore la journée</button>
			</div>
			{@render priorities(false)}
		{:else if phase === 'closed' && span}
			<div class="head">
				<p class="line">
					Journée <b>{hhmm(span.start)} → {hhmm(span.end)}</b> · <b>{duration(span.seconds)}</b>
					<small>· {duration(counted)} comptées</small>
				</p>
				<button class="plain link" onclick={openClosing}>Modifier</button>
			</div>
			{@render priorities(false)}
			{#if frame.tomorrow}<p class="carry"><span class="label">Pour demain</span><br />{frame.tomorrow}</p>{/if}
		{/if}
	</section>
{/if}

<style>
	.frame {
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding: 12px 14px;
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 10px;
	}
	h3 {
		margin: 0;
		font-size: 1rem;
	}
	.head {
		display: flex;
		flex-wrap: wrap;
		gap: 6px 14px;
		align-items: baseline;
		justify-content: space-between;
	}
	.line {
		margin: 0;
		display: flex;
		flex-wrap: wrap;
		gap: 4px 6px;
		align-items: baseline;
	}
	.label {
		font-family: var(--sans);
		font-size: 0.75rem;
		font-weight: 700;
		color: var(--muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	small,
	.muted {
		color: var(--muted);
		font-size: 0.8125rem;
	}
	.warn {
		color: var(--warn);
	}
	.warn {
		margin: 0;
		font-size: 0.875rem;
	}
	.carry {
		margin: 0;
		padding: 6px 10px;
		background: var(--soft);
		border-radius: 6px;
		white-space: pre-wrap;
		font-size: 0.9375rem;
	}
	.prios ul {
		list-style: none;
		margin: 4px 0;
		padding: 0;
	}
	.prios li {
		display: flex;
		gap: 8px;
		align-items: baseline;
		padding: 2px 0;
	}
	.prios li .text {
		flex: 1;
		min-width: 0;
		overflow-wrap: anywhere;
	}
	.prios li.done .text {
		text-decoration: line-through;
		color: var(--muted);
	}
	.prios li.carried .text {
		color: var(--muted);
	}
	.moved {
		white-space: nowrap;
	}
	.x {
		border: 0;
		background: none;
		color: var(--muted);
		cursor: pointer;
	}
	.x:hover {
		color: var(--warn);
	}
	.add,
	.inline,
	.row {
		display: flex;
		flex-wrap: wrap;
		gap: 6px 10px;
		align-items: center;
	}
	.add input {
		flex: 1;
		min-width: 180px;
	}
	input:not([type='checkbox']),
	textarea {
		font: inherit;
		font-size: 0.9375rem;
		padding: 4px 8px;
		color: var(--ink);
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 6px;
	}
	.clock {
		padding: 0;
		border: 0;
		background: none;
		font: inherit;
		font-weight: 700;
		color: var(--ink);
		text-decoration: underline dotted;
		cursor: pointer;
	}
	.link {
		padding: 0;
		background: none;
		border: 0;
		font: inherit;
		font-size: 0.875rem;
		color: var(--accent);
		text-decoration: underline;
		cursor: pointer;
	}
	.closing {
		display: flex;
		flex-direction: column;
		gap: 10px;
	}
	.times {
		display: flex;
		flex-wrap: wrap;
		gap: 6px 12px;
		align-items: center;
	}
	.sum {
		font-size: 0.875rem;
	}
	.holes-title {
		margin: 0 0 -6px;
		font-size: 0.875rem;
	}
	.holes {
		list-style: none;
		margin: 0;
		padding: 6px 10px;
		background: var(--softer);
		border-radius: 6px;
		font-size: 0.875rem;
	}
	.holes li {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 12px;
		justify-content: space-between;
		padding: 2px 0;
	}
	.tomorrow {
		display: flex;
		flex-direction: column;
		gap: 4px;
		font-size: 0.875rem;
		color: var(--muted);
	}
	.tomorrow textarea {
		width: 100%;
	}
</style>
