<script lang="ts">
	// The day's « À faire », compact, for the journal's side column: due that day and in
	// progress (active projects), by project; ticking works here too, with « Annuler ».
	import { v2, type Task } from '../api2.js';
	import { byPlace, planDay } from './plan.js';
	import { failure, placeName, reload } from './state.svelte.js';

	let { day, isToday, ondone }: { day: string; isToday: boolean; ondone?: () => void } = $props();

	const SHOWN = 8;
	let tasks = $state<Task[]>([]);
	let loaded = $state(false);
	let message = $state('');
	let undo = $state<Task | null>(null);
	let showLate = $state(false);

	let plan = $derived(planDay(tasks, day));
	let today = $derived(plan.today.slice(0, SHOWN));

	async function load() {
		try {
			tasks = await v2.openTasks(true);
		} catch (err) {
			message = failure(err, 'Tâches non chargées : ');
		} finally {
			loaded = true;
		}
	}

	$effect(() => {
		void day;
		void load();
	});

	async function finish(t: Task) {
		message = '';
		try {
			await v2.updateTask(t.id, { status: 'done' });
			tasks = tasks.filter((x) => x.id !== t.id);
			undo = t;
			ondone?.();
			reload().catch(() => {});
		} catch (err) {
			message = failure(err, 'Tâche non terminée : ');
		}
	}

	async function cancel() {
		const t = undo;
		if (!t) return;
		undo = null;
		try {
			await v2.updateTask(t.id, t.status === 'waiting' && t.waiting_on ? { status: 'waiting', waiting_on: t.waiting_on } : { status: t.status });
			await load();
			ondone?.();
		} catch (err) {
			message = failure(err, 'Annulation impossible : ');
		}
	}

	const href = (t: Task) => `${t.project_id ? `/projets/${t.project_id}` : `/espaces/${t.space_id}`}?tache=${t.id}`;
</script>

{#snippet item(t: Task)}
	<li>
		<input type="checkbox" onchange={() => finish(t)} aria-label="Terminer « {t.title} »" />
		<a href={href(t)}>{t.title}</a>
	</li>
{/snippet}

<div class="today">
	<span class="label">{isToday ? 'À faire aujourd’hui' : 'Prévu ce jour-là'} <small>{plan.today.length || ''}</small></span>
	{#if message}<p class="warn">{message}</p>{/if}
	{#if undo}
		<p class="undo">« {undo.title} » terminée. <button class="link" onclick={cancel}>Annuler</button></p>
	{/if}
	{#if !loaded}
		<p class="muted">…</p>
	{:else if today.length}
		{#each byPlace(today) as g (g.key)}
			<span class="place">{placeName(g.target)}</span>
			<ul>
				{#each g.tasks as t (t.id)}{@render item(t)}{/each}
			</ul>
		{/each}
		{#if plan.today.length > SHOWN}<small class="muted">et {plan.today.length - SHOWN} autres</small>{/if}
	{:else}
		<p class="muted">Rien d’échu ni en cours.</p>
	{/if}
	{#if plan.recentLate.length}
		<button class="link" onclick={() => (showLate = !showLate)} aria-expanded={showLate}>
			{showLate ? 'Replier les retards' : `${plan.recentLate.length} en retard cette semaine`}
		</button>
		{#if showLate}
			<ul class="late">
				{#each plan.recentLate as t (t.id)}{@render item(t)}{/each}
			</ul>
		{/if}
	{/if}
	<a class="all" href="/journee/{day}">Tout voir dans Ma journée →</a>
</div>

<style>
	.today {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	.label {
		font-size: 0.75rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--muted);
	}
	.place {
		margin-top: 6px;
		font-size: 0.75rem;
		color: var(--muted);
	}
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	li {
		display: grid;
		grid-template-columns: 18px minmax(0, 1fr);
		gap: 6px;
		align-items: start;
		padding: 2px 0;
	}
	li input {
		margin: 3px 0 0;
		accent-color: var(--accent);
	}
	li a {
		text-decoration: none;
		overflow-wrap: anywhere;
	}
	.late li a {
		color: var(--warn);
	}
	small,
	.muted {
		color: var(--muted);
		font-size: 0.8125rem;
		font-weight: 400;
	}
	p {
		margin: 0;
	}
	.warn {
		color: var(--warn);
	}
	.undo {
		font-size: 0.8125rem;
	}
	.link {
		align-self: flex-start;
		padding: 0;
		background: none;
		border: 0;
		font: inherit;
		font-size: 0.8125rem;
		color: var(--accent);
		text-decoration: underline;
		cursor: pointer;
	}
	.all {
		margin-top: 6px;
		font-size: 0.8125rem;
		color: var(--accent);
	}
</style>
