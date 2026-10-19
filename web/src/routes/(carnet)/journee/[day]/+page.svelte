<script lang="ts">
	import { onDestroy } from 'svelte';
	import { page } from '$app/state';
	import EventRow from '#lib/carnet/EventRow.svelte';
	import DayPlan from '#lib/carnet/DayPlan.svelte';
	import { v2, type AgendaEvent, type CountedBlock, type DayReport, type OverlapMode, type Target, type Task, type TimeBlock } from '#lib/api2.js';
	import {
		carnet,
		duration,
		failure,
		isDay,
		longDate,
		placeName,
		shiftDay,
		timeZone,
		todayIso
	} from '#lib/carnet/state.svelte.js';

	let day = $derived(isDay(page.params.day ?? '') ? (page.params.day as string) : '');
	let report = $state<DayReport | null>(null);
	let meetings = $state<AgendaEvent[]>([]);
	let openTasks = $state<Task[]>([]); // open tasks of active projects: the day's plan
	let message = $state('');
	let info = $state('');
	let taskTitles = $state<Record<string, string>>({});
	let now = $state(Date.now());

	// Start a timer
	let startPlace = $state('');
	let startTasks = $state<Task[]>([]);
	let startTask = $state('');
	let startNote = $state('');

	// Add a block by hand
	let adding = $state(false);
	let addDraft = $state({ start: '09:00', end: '10:00', place: '', note: '' });

	// Edit a block
	let editId = $state<string | null>(null);
	let editDraft = $state({ start: '', end: '', mode: 'shared' as OverlapMode, note: '' });

	// Stale timers: the time they really stopped
	let staleStop = $state<Record<string, string>>({});

	const MODES: Record<OverlapMode, string> = {
		shared: 'Partagé avec ce qui tourne en même temps',
		both: 'Compté en entier, même en parallèle',
		exclusive: 'Seul compté sur ce créneau'
	};

	const tick = setInterval(() => (now = Date.now()), 1000);
	onDestroy(() => clearInterval(tick));

	$effect(() => {
		const current = day;
		report = null;
		message = '';
		info = '';
		editId = null;
		if (current) void load(current);
	});

	async function load(current = day) {
		try {
			const [r, timers, doing, agenda] = await Promise.all([
				v2.day(current, timeZone()),
				v2.timers(),
				v2.openTasks(true),
				v2.agenda(current, 1, timeZone()).catch(() => [] as AgendaEvent[])
			]);
			if (current !== day) return;
			report = r;
			meetings = agenda.filter((m) => !m.all_day);
			carnet.timers = timers;
			openTasks = doing;
			for (const t of doing) taskTitles[t.id] = t.title;
			void fetchTitles([...r.blocks.map((b) => b.block.task_id), ...timers.map((t) => t.task_id)]);
		} catch (err) {
			if (current === day) message = failure(err, 'Journée non chargée : ');
		}
	}

	async function fetchTitles(ids: (string | null)[]) {
		for (const id of new Set(ids)) {
			if (!id || taskTitles[id]) continue;
			try {
				taskTitles[id] = (await v2.task(id)).title;
			} catch {
				taskTitles[id] = 'Tâche supprimée';
			}
		}
	}

	async function attempt<T>(what: string, action: () => Promise<T>): Promise<T | undefined> {
		message = '';
		info = '';
		try {
			return await action();
		} catch (err) {
			message = failure(err, `${what} : `);
			return undefined;
		}
	}

	// ------------------------------------------------------------ time helpers

	function clock(iso: string): string {
		return new Date(iso).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
	}

	/** « 14:05 » on the page's day -> ISO instant; an end before the start is the next day. */
	function instant(hhmm: string, after?: string): string {
		let date = new Date(`${day}T${hhmm}:00`);
		if (after && date <= new Date(after)) date = new Date(date.getTime() + 86_400_000);
		return date.toISOString();
	}

	function elapsed(iso: string): string {
		const total = Math.max(0, Math.floor((now - new Date(iso).getTime()) / 1000));
		const h = Math.floor(total / 3600);
		const m = Math.floor((total % 3600) / 60);
		const s = total % 60;
		return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
	}

	function rawSeconds(c: CountedBlock): number {
		return Math.round((new Date(c.end).getTime() - new Date(c.start).getTime()) / 1000);
	}

	/** "p:<project id>" or "s:<space id>" from a select -> a target. */
	function target(value: string): Target | null {
		if (value.startsWith('p:')) return { project_id: value.slice(2) };
		if (value.startsWith('s:')) return { space_id: value.slice(2) };
		return null;
	}

	function label(b: TimeBlock): string {
		const where = placeName(b);
		return b.task_id ? `${where} · ${taskTitles[b.task_id] ?? '…'}` : where;
	}

	// ------------------------------------------------------------ timers

	async function pickStartPlace(value: string) {
		startPlace = value;
		startTask = '';
		startTasks = [];
		const t = target(value);
		if (t?.project_id) {
			const tasks = await attempt('Tâches non chargées', () => v2.projectTasks(t.project_id!));
			if (tasks && startPlace === value) startTasks = tasks;
		}
	}

	async function start(event: SubmitEvent) {
		event.preventDefault();
		const t = target(startPlace);
		if (!t) return;
		const body = startTask ? { task_id: startTask } : t;
		const timer = await attempt('Minuteur non démarré', () => v2.startTimer({ ...body, note: startNote.trim() || null }));
		if (!timer) return;
		if (startTask) taskTitles[startTask] = startTasks.find((x) => x.id === startTask)?.title ?? '';
		startNote = '';
		await load();
	}

	async function startOnTask(task: Task) {
		const timer = await attempt('Minuteur non démarré', () => v2.startTimer({ task_id: task.id }));
		if (timer) await load();
	}

	async function stop(timer: TimeBlock, at?: string) {
		const stopped = await attempt('Minuteur non arrêté', () => v2.stopTimer(timer.id, at));
		if (stopped) await load();
	}

	function stopStale(timer: TimeBlock) {
		const hhmm = staleStop[timer.id];
		if (!hhmm) return;
		const startDay = new Date(timer.start_at);
		const local = new Date(startDay.getTime() - startDay.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
		let at = new Date(`${local}T${hhmm}:00`);
		if (at <= startDay) at = new Date(at.getTime() + 86_400_000);
		void stop(timer, at.toISOString());
	}

	// ------------------------------------------------------------ blocks

	async function addBlock(event: SubmitEvent) {
		event.preventDefault();
		const t = target(addDraft.place);
		if (!t) {
			message = 'Choisis un projet ou un espace.';
			return;
		}
		const start = instant(addDraft.start);
		const block = await attempt('Créneau non ajouté', () =>
			v2.addBlock({ ...t, start, end: instant(addDraft.end, start), note: addDraft.note.trim() || null })
		);
		if (!block) return;
		adding = false;
		addDraft = { start: addDraft.end, end: addDraft.end, place: addDraft.place, note: '' };
		await load();
	}

	function edit(c: CountedBlock) {
		editId = c.block.id;
		editDraft = {
			start: clock(c.block.start_at),
			end: c.block.end_at ? clock(c.block.end_at) : '',
			mode: c.block.overlap_mode,
			note: c.block.note ?? ''
		};
	}

	async function saveBlock(c: CountedBlock) {
		const b = c.block;
		const patch: Parameters<typeof v2.updateBlock>[1] = {};
		const startDay = new Date(b.start_at);
		const local = new Date(startDay.getTime() - startDay.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
		if (editDraft.start !== clock(b.start_at)) patch.start = new Date(`${local}T${editDraft.start}:00`).toISOString();
		const start = patch.start ?? b.start_at;
		if (b.end_at && editDraft.end && editDraft.end !== clock(b.end_at)) {
			let end = new Date(`${local}T${editDraft.end}:00`);
			if (end <= new Date(start)) end = new Date(end.getTime() + 86_400_000);
			patch.end = end.toISOString();
		} else if (patch.start && b.end_at) {
			patch.end = b.end_at;
		}
		if (editDraft.mode !== b.overlap_mode) patch.overlap_mode = editDraft.mode;
		if (editDraft.note.trim() !== (b.note ?? '')) patch.note = editDraft.note.trim() || null;
		if (Object.keys(patch).length) {
			const saved = await attempt('Créneau non modifié', () => v2.updateBlock(b.id, patch));
			if (!saved) return;
		}
		editId = null;
		await load();
	}

	async function removeBlock(c: CountedBlock) {
		if (!confirm(`Supprimer le créneau ${clock(c.start)}–${clock(c.end)} (${label(c.block)}) ?`)) return;
		const ok = await attempt('Créneau non supprimé', async () => {
			await v2.deleteBlock(c.block.id);
			return true;
		});
		if (ok) {
			editId = null;
			await load();
		}
	}

	async function validate() {
		const r = await attempt('Journée non validée', () => v2.validateDay(day, timeZone()));
		if (!r) return;
		await load();
		info = r.validated ? `${r.validated} créneau${r.validated > 1 ? 'x' : ''} validé${r.validated > 1 ? 's' : ''}.` : 'Rien de nouveau à valider.';
	}

	let byProject = $derived.by(() => {
		if (!report) return [];
		const rows = Object.entries(report.by_project)
			.filter(([, s]) => s >= 30)
			.map(([key, seconds]) => ({
				key,
				name: key ? placeName({ project_id: key, space_id: '' }) : 'Sans projet',
				seconds
			}));
		return rows.sort((a, b) => b.seconds - a.seconds);
	});
	let maxSeconds = $derived(Math.max(1, ...byProject.map((r) => r.seconds)));
	let unchecked = $derived(report?.blocks.some((c) => !c.block.validated && !c.running) ?? false);
</script>

{#snippet places()}
	<option value="">Choisir…</option>
	{#each carnet.tree?.spaces ?? [] as space (space.id)}
		<optgroup label={space.name}>
			<option value="s:{space.id}">{space.name} (sans projet)</option>
			{#each space.projects as project (project.id)}
				<option value="p:{project.id}">{project.parent_id ? '  ' : ''}{project.name}</option>
			{/each}
		</optgroup>
	{/each}
{/snippet}

<svelte:head><title>Ma journée · P.IGE</title></svelte:head>

<div class="wrap">
	{#if !day}
		<p>Date invalide. <a href="/journee/{todayIso()}">Aller à aujourd’hui</a></p>
	{:else}
		<header>
			<div class="days">
				<a href="/journee/{shiftDay(day, -1)}">‹ {longDate(shiftDay(day, -1))}</a>
				{#if day !== todayIso()}<a href="/journee/{todayIso()}">Aujourd’hui</a>{/if}
				<a href="/journee/{shiftDay(day, 1)}">{longDate(shiftDay(day, 1))} ›</a>
			</div>
			<h1>Ma journée <span class="date">{longDate(day)}</span></h1>
		</header>

		{#if message}<p class="message" role="alert">{message}</p>{/if}
		{#if info}<p class="info" role="status">{info}</p>{/if}

		<div class="today">
			{#if meetings.length}
				<section aria-labelledby="meet-title">
					<h2 id="meet-title">Rendez-vous <small>{meetings.length}</small></h2>
					{#each meetings as m (m.id)}
						<EventRow
							event={m}
							onchanged={(u) => {
								meetings = meetings.map((x) => (x.id === u.id ? u : x));
								if (u.block_id && !m.block_id) void load();
							}}
						/>
					{/each}
				</section>
			{/if}
			<DayPlan tasks={openTasks} {day} isToday={day === todayIso()} onchanged={() => void load()} onstart={startOnTask} />
		</div>

		<h2 class="time-title">Temps</h2>
		<div class="cols">
			<div class="main">
				<section aria-labelledby="timers-title">
					<h2 id="timers-title">Minuteurs en cours <small>{carnet.timers.length || ''}</small></h2>
					{#each carnet.timers as timer (timer.id)}
						{@const stale = report?.stale_timers.some((s) => s.id === timer.id)}
						<div class="timer" class:stale>
							<span class="pulse" aria-hidden="true"></span>
							<span class="what">
								<b>{label(timer)}</b>
								<small>depuis {clock(timer.start_at)}{#if timer.note} · {timer.note}{/if}</small>
							</span>
							<span class="elapsed" aria-label="Temps écoulé">{elapsed(timer.start_at)}</span>
							<button class="btn" onclick={() => stop(timer)}>Arrêter</button>
						</div>
						{#if stale}
							<form class="stale-fix" onsubmit={(e) => { e.preventDefault(); stopStale(timer); }}>
								<span>Lancé il y a plus de 16 h, sans doute oublié. Arrêté en réalité à</span>
								<input type="time" bind:value={staleStop[timer.id]} required aria-label="Heure réelle d’arrêt" />
								<button class="btn">Arrêter à cette heure</button>
							</form>
						{/if}
					{:else}
						<p class="muted">Aucun minuteur ne tourne.</p>
					{/each}

					<form class="start" onsubmit={start}>
						<select value={startPlace} onchange={(e) => pickStartPlace((e.currentTarget as HTMLSelectElement).value)} aria-label="Projet ou espace">
							{@render places()}
						</select>
						{#if startTasks.length}
							<select bind:value={startTask} aria-label="Tâche (facultatif)">
								<option value="">Sans tâche précise</option>
								{#each startTasks as task (task.id)}<option value={task.id}>{task.title}</option>{/each}
							</select>
						{/if}
						<input bind:value={startNote} placeholder="Note (facultatif)" aria-label="Note" />
						<button class="btn primary" disabled={!startPlace}>▶ Démarrer</button>
					</form>
					<p class="hint">Plusieurs minuteurs peuvent tourner en même temps : le temps commun est partagé entre eux.</p>

				</section>


				<section aria-labelledby="blocks-title">
					<h2 id="blocks-title">Créneaux <small>{report ? report.blocks.length : ''}</small></h2>
					{#if !report}
						<p class="muted">Chargement…</p>
					{:else}
						<ol class="blocks">
							{#each report.blocks as c (c.block.id)}
								{@const raw = rawSeconds(c)}
								<li class:running={c.running}>
									<div class="block">
										<span class="hours">{clock(c.start)}–{c.running ? '…' : clock(c.end)}</span>
										<span class="what">
											<b>{label(c.block)}</b>
											{#if c.block.note}<small>{c.block.note}</small>{/if}
										</span>
										<span class="counted">
											{duration(c.counted_seconds)}
											{#if c.counted_seconds < raw - 30}<small title="Temps partagé avec un autre créneau">sur {duration(raw)}</small>{/if}
										</span>
										<span class="flags">
											{#if c.block.validated}<span title="Validé">✓</span>{/if}
											{#if !c.running}<button class="edit" onclick={() => (editId === c.block.id ? (editId = null) : edit(c))} aria-expanded={editId === c.block.id} aria-label="Modifier le créneau">✎</button>{/if}
										</span>
									</div>
									{#if editId === c.block.id}
										<form class="edit-form" onsubmit={(e) => { e.preventDefault(); void saveBlock(c); }}>
											<label>De <input type="time" bind:value={editDraft.start} required /></label>
											<label>à <input type="time" bind:value={editDraft.end} required /></label>
											<label class="wide">Chevauchement
												<select bind:value={editDraft.mode}>
													{#each Object.entries(MODES) as [value, text] (value)}<option {value}>{text}</option>{/each}
												</select>
											</label>
											<label class="wide">Note <input bind:value={editDraft.note} /></label>
											<div class="row-actions">
												<button class="btn primary">Enregistrer</button>
												<button type="button" class="btn" onclick={() => (editId = null)}>Annuler</button>
												<button type="button" class="btn danger" onclick={() => removeBlock(c)}>Supprimer</button>
											</div>
										</form>
									{/if}
								</li>
							{:else}
								<li class="muted empty">Aucun créneau ce jour-là.</li>
							{/each}
						</ol>
						{#if adding}
							<form class="edit-form add" onsubmit={addBlock}>
								<label>De <input type="time" bind:value={addDraft.start} required /></label>
								<label>à <input type="time" bind:value={addDraft.end} required /></label>
								<label class="wide">Pour
									<select bind:value={addDraft.place} required>{@render places()}</select>
								</label>
								<label class="wide">Note <input bind:value={addDraft.note} /></label>
								<div class="row-actions">
									<button class="btn primary">Ajouter</button>
									<button type="button" class="btn" onclick={() => (adding = false)}>Annuler</button>
								</div>
							</form>
						{:else}
							<button class="plain link" onclick={() => (adding = true)}>+ Ajouter un créneau à la main</button>
						{/if}
					{/if}
				</section>
			</div>

			<aside class="summary" aria-labelledby="summary-title">
				<h2 id="summary-title">Bilan</h2>
				{#if report}
					<p class="presence"><b>{duration(report.presence_seconds)}</b> <span>de présence</span></p>
					{#each byProject as row (row.key)}
						<div class="bar-row">
							<span class="bar-name">{row.name}</span>
							<span class="bar-time">{duration(row.seconds)}</span>
							<span class="bar" aria-hidden="true"><span style="width: {(row.seconds / maxSeconds) * 100}%"></span></span>
						</div>
					{:else}
						<p class="muted">Pas encore de temps compté.</p>
					{/each}
					{#if report.blocks.length}
						<button class="btn validate" onclick={validate} disabled={!unchecked}>
							{unchecked ? 'Valider la journée' : 'Journée validée ✓'}
						</button>
					{/if}
				{/if}
			</aside>
		</div>
	{/if}
</div>

<style>
	.wrap {
		padding: 22px 32px 48px;
		display: flex;
		flex-direction: column;
		gap: 16px;
	}
	.days {
		display: flex;
		gap: 14px;
		font-size: 0.875rem;
	}
	.days a {
		color: var(--muted);
	}
	h1 {
		font-size: 1.875rem;
		margin: 4px 0 0;
	}
	h1 .date {
		font-weight: 400;
		font-style: italic;
		color: var(--muted);
		font-size: 1.25rem;
	}
	h2 {
		font-size: 1.125rem;
		padding-bottom: 4px;
		border-bottom: var(--rule);
		margin: 0 0 4px;
	}
	h2 small,
	small,
	.muted {
		font-family: var(--sans);
		font-weight: 400;
		color: var(--muted);
		font-size: 0.875rem;
	}
	.message,
	.info {
		margin: 0;
		padding: 8px 12px;
		border-radius: 8px;
	}
	.message {
		color: var(--warn);
		background: var(--warn-soft);
	}
	.info {
		background: var(--soft);
	}
	.cols {
		display: grid;
		grid-template-columns: minmax(0, 1.6fr) minmax(240px, 1fr);
		gap: 28px;
		align-items: start;
	}
	.main {
		display: flex;
		flex-direction: column;
		gap: 26px;
	}
	select,
	input {
		font: inherit;
		color: var(--ink);
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 6px;
		padding: 5px 8px;
		min-width: 0;
	}
	.plain {
		padding: 0;
		font: inherit;
		background: none;
		border: 0;
	}
	.link {
		margin-top: 8px;
		color: var(--accent);
		font-size: 0.875rem;
		text-decoration: underline;
	}
	.timer {
		display: grid;
		grid-template-columns: 12px minmax(0, 1fr) auto auto;
		gap: 12px;
		align-items: center;
		padding: 10px 0;
		border-bottom: 1px solid var(--line);
	}
	.pulse {
		width: 10px;
		height: 10px;
		border-radius: 50%;
		background: var(--accent);
		animation: pulse 2s ease-in-out infinite;
	}
	.timer.stale .pulse {
		background: var(--warn);
	}
	@keyframes pulse {
		50% {
			opacity: 0.35;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.pulse {
			animation: none;
		}
	}
	.what {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}
	.what b {
		overflow-wrap: anywhere;
	}
	.elapsed {
		font-family: var(--serif);
		font-size: 1.375rem;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}
	.stale-fix {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		align-items: center;
		padding: 8px 12px;
		font-size: 0.875rem;
		color: var(--warn);
		background: var(--warn-soft);
		border-radius: 8px;
	}
	.start {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		margin-top: 12px;
	}
	.start select {
		flex: 1 1 200px;
	}
	.start input {
		flex: 1 1 140px;
	}
	.hint {
		margin: 6px 0 0;
		font-size: 0.8125rem;
		color: var(--muted);
	}
	.blocks {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.blocks > li {
		border-bottom: 1px solid var(--line);
	}
	.block {
		display: grid;
		grid-template-columns: 100px minmax(0, 1fr) auto 52px;
		gap: 10px;
		align-items: baseline;
		padding: 9px 0;
	}
	.running .hours {
		color: var(--accent);
	}
	.hours,
	.counted {
		font-variant-numeric: tabular-nums;
	}
	.counted {
		text-align: right;
		font-weight: 700;
	}
	.counted small {
		display: block;
		font-weight: 400;
	}
	.flags {
		display: flex;
		gap: 4px;
		justify-content: flex-end;
		color: var(--accent);
	}
	.edit {
		width: 28px;
		height: 28px;
		color: var(--muted);
		background: none;
		border: 0;
		border-radius: 6px;
	}
	.edit:hover {
		background: var(--soft);
	}
	.edit-form {
		display: flex;
		flex-wrap: wrap;
		gap: 10px;
		align-items: center;
		padding: 10px 12px 14px;
		margin-bottom: 8px;
		background: var(--surface);
		border-radius: 8px;
		font-size: 0.875rem;
	}
	.edit-form label {
		display: flex;
		gap: 6px;
		align-items: center;
	}
	.edit-form .wide {
		flex: 1 1 100%;
	}
	.edit-form .wide select,
	.edit-form .wide input {
		flex: 1;
	}
	.add {
		margin-top: 10px;
	}
	.row-actions {
		display: flex;
		gap: 8px;
		flex: 1 1 100%;
	}
	.danger {
		margin-left: auto;
		color: var(--warn);
	}
	.empty {
		padding: 10px 0;
	}
	.summary {
		position: sticky;
		top: 16px;
		display: flex;
		flex-direction: column;
		gap: 10px;
		padding: 16px 18px;
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 10px;
	}
	.presence {
		margin: 0;
	}
	.presence b {
		font-family: var(--serif);
		font-size: 2rem;
	}
	.presence span {
		color: var(--muted);
	}
	.bar-row {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		gap: 2px 8px;
		font-size: 0.875rem;
	}
	.bar-name {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.bar-time {
		font-variant-numeric: tabular-nums;
		font-weight: 700;
	}
	.bar {
		grid-column: 1 / -1;
		height: 6px;
		background: var(--softer);
		border-radius: 3px;
	}
	.bar span {
		display: block;
		height: 100%;
		background: var(--accent);
		border-radius: 3px;
	}
	.validate {
		margin-top: 6px;
	}
	@media (max-width: 900px) {
		.cols {
			grid-template-columns: 1fr;
		}
		.summary {
			position: static;
			order: -1;
		}
	}
	@media (max-width: 600px) {
		.wrap {
			padding: 16px;
		}
		.timer {
			grid-template-columns: 12px minmax(0, 1fr) auto;
		}
		.timer .btn {
			grid-column: 2 / -1;
			justify-self: start;
		}
		.block {
			grid-template-columns: auto minmax(0, 1fr) auto 44px;
			gap: 8px;
			font-size: 0.9375rem;
		}
		.hours {
			white-space: nowrap;
			font-size: 0.8125rem;
		}
		.flags .edit {
			width: 24px;
		}
	}
	.today {
		display: flex;
		flex-direction: column;
		gap: 16px;
	}
	.time-title {
		margin-top: 8px;
		font-size: 1.5rem;
	}
</style>
