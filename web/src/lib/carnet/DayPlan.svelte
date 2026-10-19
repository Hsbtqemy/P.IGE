<script lang="ts">
	// What to do that day, by project: due that day and in progress first, then what is late
	// (the oldest folded), what comes in the next days, what others owe.
	import { v2, type Task } from '../api2.js';
	import { byPlace, daysBetween, planDay, RECENT_LATE_DAYS } from './plan.js';
	import { carnet, failure, placeName, reload } from './state.svelte.js';

	let {
		tasks,
		day,
		isToday,
		onchanged,
		onstart
	}: {
		tasks: Task[];
		day: string;
		isToday: boolean;
		onchanged: () => void;
		onstart: (task: Task) => void;
	} = $props();

	let plan = $derived(planDay(tasks, day));
	let showOld = $state(false);
	let showWaiting = $state(false);
	let message = $state('');
	let info = $state('');

	function shift(delta: number): string {
		const d = new Date(`${day}T12:00:00Z`);
		d.setUTCDate(d.getUTCDate() + delta);
		return d.toISOString().slice(0, 10);
	}

	function short(iso: string): string {
		const diff = daysBetween(day, iso);
		if (diff === 1) return 'demain';
		if (diff > 1 && diff < 7) return new Date(`${iso}T12:00:00`).toLocaleDateString('fr-FR', { weekday: 'long' });
		return new Date(`${iso}T12:00:00`).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' });
	}

	function ago(iso: string | undefined): string {
		if (!iso) return '';
		const d = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
		return d < 1 ? 'aujourd’hui' : d === 1 ? 'hier' : d < 31 ? `${d} j` : d < 365 ? `${Math.floor(d / 30.4)} mois` : `${Math.floor(d / 365)} an${d >= 730 ? 's' : ''}`;
	}

	function why(t: Task): string {
		const due = t.due_date;
		if (due === day) return isToday ? 'pour aujourd’hui' : 'pour ce jour';
		if (due && due < day) {
			const late = daysBetween(due, day);
			return `en retard de ${late} j${t.status === 'in_progress' ? ' · en cours' : ''}`;
		}
		if (due && due > day) return `pour ${short(due)}`;
		if (t.status === 'in_progress') return `en cours depuis ${ago(t.status_since)}`;
		if (t.status === 'waiting') {
			const who = carnet.people.find((p) => p.id === t.waiting_on)?.display_name ?? 'quelqu’un';
			return `attend ${who} depuis ${ago(t.status_since)}`;
		}
		return '';
	}

	async function act(what: string, action: () => Promise<unknown>, done: string) {
		message = '';
		info = '';
		try {
			await action();
			info = done;
			onchanged();
			reload().catch(() => {});
		} catch (err) {
			message = failure(err, `${what} : `);
		}
	}

	function finish(t: Task) {
		void act('Tâche non terminée', () => v2.updateTask(t.id, { status: 'done' }), `« ${t.title} » terminée.`);
	}

	function postpone(t: Task, value: string) {
		if (!value) return;
		const due = value === 'none' ? '' : shift(Number(value));
		const label = value === 'none' ? 'sans échéance' : `pour ${short(due)}`;
		void act('Échéance non changée', () => v2.updateTask(t.id, { due_date: due }), `« ${t.title} » : ${label}.`);
	}

	function backToDo(t: Task) {
		void act('Tâche non modifiée', () => v2.updateTask(t.id, { status: 'open' }), `« ${t.title} » remise dans « À faire ».`);
	}

	const href = (t: Task) => `${t.project_id ? `/projets/${t.project_id}` : `/espaces/${t.space_id}`}?tache=${t.id}`;
	const running = (t: Task) => carnet.timers.some((x) => x.task_id === t.id);
</script>

{#snippet row(t: Task, late = false)}
	<li class="row" class:late>
		<input type="checkbox" class="check" onchange={() => finish(t)} aria-label="Terminer « {t.title} »" />
		<a class="what" href={href(t)}>
			<span>{t.title}</span>
			<small>{why(t)}{t.steps_total ? ` · ${t.steps_done}/${t.steps_total}` : ''}</small>
		</a>
		<span class="tools">
			{#if isToday && !running(t)}
				<button class="play" onclick={() => onstart(t)} aria-label="Démarrer un minuteur sur « {t.title} »" title="Démarrer un minuteur">▶</button>
			{/if}
			<select aria-label="Reporter « {t.title} »" title="Reporter" onchange={(e) => postpone(t, (e.currentTarget as HTMLSelectElement).value)}>
				<option value="">Reporter…</option>
				<option value="1">à demain</option>
				<option value="7">dans une semaine</option>
				<option value="none">sans échéance</option>
			</select>
			{#if t.status === 'in_progress'}
				<button class="plain back" onclick={() => backToDo(t)} title="Ce n’est pas en cours : remettre dans « À faire »">Remettre à faire</button>
			{/if}
		</span>
	</li>
{/snippet}

{#snippet grouped(list: Task[], late = false)}
	{#each byPlace(list) as g (g.key)}
		<div class="place">
			<h3><a href={g.target.project_id ? `/projets/${g.target.project_id}` : `/espaces/${g.target.space_id}`}>{placeName(g.target)}</a></h3>
			<ul>
				{#each g.tasks as t (t.id)}{@render row(t, late)}{/each}
			</ul>
		</div>
	{/each}
{/snippet}

<section class="plan" aria-labelledby="plan-title">
	<h2 id="plan-title">{isToday ? 'À faire aujourd’hui' : 'À faire ce jour-là'} <small>{plan.today.length || ''}</small></h2>
	{#if message}<p class="warn" role="alert">{message}</p>{/if}
	{#if info}<p class="info" role="status">{info}</p>{/if}
	{#if plan.today.length}
		{@render grouped(plan.today)}
	{:else}
		<p class="muted">
			Rien d’échu {isToday ? 'aujourd’hui' : 'ce jour-là'} ni en cours.{#if plan.ahead.length} Voir les prochains jours ci-dessous.{/if}
		</p>
	{/if}

	{#if plan.recentLate.length || plan.oldLate.length}
		<h3 class="sub">En retard <small>{plan.recentLate.length + plan.oldLate.length}</small></h3>
		{#if plan.recentLate.length}{@render grouped(plan.recentLate, true)}{/if}
		{#if plan.oldLate.length}
			<button class="plain more" onclick={() => (showOld = !showOld)} aria-expanded={showOld}>
				{showOld ? 'Replier' : `${plan.oldLate.length} en retard depuis plus de ${RECENT_LATE_DAYS} jours`}
			</button>
			{#if showOld}{@render grouped(plan.oldLate, true)}{/if}
		{/if}
	{/if}

	{#if plan.ahead.length}
		<h3 class="sub">Prochains jours <small>{plan.ahead.length}</small></h3>
		<ul class="ahead">
			{#each plan.ahead as t (t.id)}
				<li>
					<span class="when">{short(t.due_date ?? '')}</span>
					<a href={href(t)}>{t.title}</a>
					<small>{placeName(t)}</small>
				</li>
			{/each}
		</ul>
	{/if}

	{#if plan.waiting.length}
		<button class="plain more" onclick={() => (showWaiting = !showWaiting)} aria-expanded={showWaiting}>
			{showWaiting ? 'Replier' : `En attente des autres : ${plan.waiting.length}`}
		</button>
		{#if showWaiting}{@render grouped(plan.waiting)}{/if}
	{/if}
</section>

<style>
	.plan {
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding: 16px 18px;
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 12px;
	}
	h2 {
		font-size: 1.25rem;
		padding-bottom: 4px;
		border-bottom: var(--rule);
	}
	h3 {
		margin: 6px 0 0;
		font-family: var(--sans);
		font-size: 0.8125rem;
		font-weight: 700;
		color: var(--muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	h3 a {
		text-decoration: none;
	}
	h3.sub {
		margin-top: 12px;
		font-family: var(--serif);
		font-size: 1.0625rem;
		text-transform: none;
		letter-spacing: 0;
		color: var(--ink);
	}
	small,
	.muted {
		color: var(--muted);
		font-size: 0.8125rem;
		font-weight: 400;
	}
	.muted {
		margin: 0;
		font-size: 0.875rem;
	}
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.row {
		display: grid;
		grid-template-columns: 24px minmax(0, 1fr) auto;
		gap: 8px;
		align-items: center;
		padding: 6px 0;
		border-bottom: 1px solid var(--line);
	}
	.row.late .what small {
		color: var(--warn);
	}
	.check {
		width: 18px;
		height: 18px;
		accent-color: var(--accent);
	}
	.what {
		display: flex;
		flex-direction: column;
		min-width: 0;
		text-decoration: none;
	}
	.what span {
		overflow-wrap: anywhere;
	}
	.tools {
		display: flex;
		gap: 6px;
		align-items: center;
	}
	.play {
		width: 28px;
		height: 28px;
		border: 1px solid var(--line);
		border-radius: 50%;
		background: var(--surface);
		color: var(--accent);
		cursor: pointer;
	}
	select {
		font: inherit;
		font-size: 0.8125rem;
		color: var(--muted);
		background: transparent;
		border: 1px solid var(--line);
		border-radius: 6px;
		padding: 3px 4px;
		max-width: 8.5em;
	}
	.back,
	.more {
		padding: 2px 0;
		background: none;
		border: 0;
		font: inherit;
		font-size: 0.8125rem;
		color: var(--muted);
		text-decoration: underline;
		cursor: pointer;
		align-self: flex-start;
	}
	.more {
		color: var(--accent);
		font-size: 0.875rem;
	}
	.ahead li {
		display: grid;
		grid-template-columns: 6.5em minmax(0, 1fr) auto;
		gap: 8px;
		padding: 4px 0;
		font-size: 0.9375rem;
		align-items: baseline;
	}
	.ahead a {
		text-decoration: none;
		overflow-wrap: anywhere;
	}
	.when {
		color: var(--muted);
		font-size: 0.8125rem;
	}
	.warn,
	.info {
		margin: 0;
		padding: 6px 10px;
		border-radius: 8px;
		font-size: 0.875rem;
	}
	.warn {
		color: var(--warn);
		background: var(--warn-soft);
	}
	.info {
		background: var(--soft);
	}
	@media (max-width: 600px) {
		.row {
			grid-template-columns: 24px minmax(0, 1fr);
		}
		.tools {
			grid-column: 2;
		}
		.ahead li {
			grid-template-columns: 5.5em minmax(0, 1fr);
		}
		.ahead small {
			grid-column: 2;
		}
	}
</style>
