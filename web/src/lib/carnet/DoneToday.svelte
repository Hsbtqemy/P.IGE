<script lang="ts">
	// What was finished on a day (by the moment it was ticked), grouped by project: the day's
	// record in the journal and in Ma journée. « Rouvrir » undoes a click.
	import { v2, type Priority, type Task } from '../api2.js';
	import { byPlace } from './plan.js';
	import { failure, placeName, reload, shiftDay, timeZone } from './state.svelte.js';

	let {
		day,
		title = 'Fait ce jour-là',
		refreshKey = 0,
		onreopen
	}: { day: string; title?: string; refreshKey?: number; onreopen?: () => void } = $props();

	let tasks = $state<Task[]>([]);
	// Priorities of the day's frame written as plain text and ticked: done too, though not tasks
	// (a priority that is a task shows up as that task).
	let priorities = $state<Priority[]>([]);
	let all = $state<Priority[]>([]);
	let message = $state('');

	async function load(target: string) {
		try {
			const start = new Date(`${target}T00:00:00`);
			const end = new Date(`${shiftDay(target, 1)}T00:00:00`);
			const [list, frame] = await Promise.all([
				v2.doneTasks(start.toISOString()),
				v2.frame(target, timeZone()).catch(() => null)
			]);
			if (target !== day) return;
			tasks = list.filter((t) => t.done_at && new Date(t.done_at) < end);
			all = frame?.priorities ?? [];
			priorities = all.filter((p) => !p.task_id && p.done);
		} catch (err) {
			if (target === day) message = failure(err, 'Tâches terminées non chargées : ');
		}
	}

	$effect(() => {
		void refreshKey;
		void load(day);
	});

	async function reopen(t: Task) {
		message = '';
		try {
			await v2.updateTask(t.id, { status: 'open' });
			tasks = tasks.filter((x) => x.id !== t.id);
			onreopen?.();
			reload().catch(() => {});
		} catch (err) {
			message = failure(err, 'Tâche non rouverte : ');
		}
	}

	async function reopenPriority(p: Priority) {
		message = '';
		try {
			const next = all.map((x) => ({ text: x.text, task_id: x.task_id, done: x === p ? false : x.done, carried: x.carried ?? false }));
			const frame = await v2.updateFrame(day, timeZone(), { priorities: next });
			all = frame.priorities;
			priorities = all.filter((x) => !x.task_id && x.done);
			onreopen?.();
		} catch (err) {
			message = failure(err, 'Priorité non rouverte : ');
		}
	}

	const clock = (iso: string) => new Date(iso).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
</script>

{#if tasks.length || priorities.length || message}
	<section class="done" aria-label={title}>
		<h2>
			{title}
			<small>
				{#if tasks.length}{tasks.length} tâche{tasks.length > 1 ? 's' : ''} terminée{tasks.length > 1 ? 's' : ''}{/if}{#if tasks.length && priorities.length}{' · '}{/if}{#if priorities.length}{priorities.length} priorité{priorities.length > 1 ? 's' : ''}{/if}
			</small>
		</h2>
		{#if message}<p class="warn" role="alert">{message}</p>{/if}
		{#if priorities.length}
			<div class="place">
				<h3>Priorités du jour</h3>
				<ul>
					{#each priorities as p, i (i)}
						<li>
							<span class="tick" aria-hidden="true">✓</span>
							<span class="title">{p.text}</span>
							<small></small>
							<button class="reopen" onclick={() => reopenPriority(p)} title="Cochée par erreur ? La remettre à faire">Rouvrir</button>
						</li>
					{/each}
				</ul>
			</div>
		{/if}
				{#each byPlace(tasks) as g (g.key)}
			<div class="place">
				<h3>
					<a href={g.target.project_id ? `/projets/${g.target.project_id}` : `/espaces/${g.target.space_id}`}>{placeName(g.target)}</a>
				</h3>
				<ul>
					{#each g.tasks as t (t.id)}
						<li>
							<span class="tick" aria-hidden="true">✓</span>
							<span class="title">{t.title}</span>
							<small>{t.done_at ? clock(t.done_at) : ''}</small>
							<button class="reopen" onclick={() => reopen(t)} title="Cochée par erreur ? La remettre à faire">Rouvrir</button>
						</li>
					{/each}
				</ul>
			</div>
		{/each}
	</section>
{/if}

<style>
	.done {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	h2 {
		font-size: 1.0625rem;
		margin: 0;
	}
	h2 small,
	small {
		font-family: var(--sans);
		font-weight: 400;
		font-size: 0.8125rem;
		color: var(--muted);
	}
	h3 {
		margin: 4px 0 0;
		font-family: var(--sans);
		font-size: 0.75rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--muted);
	}
	h3 a {
		text-decoration: none;
	}
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	li {
		display: grid;
		grid-template-columns: 18px minmax(0, 1fr) auto auto;
		gap: 8px;
		align-items: baseline;
		padding: 3px 0;
		font-size: 0.9375rem;
	}
	.tick {
		color: var(--accent);
		font-weight: 700;
	}
	.title {
		overflow-wrap: anywhere;
	}
	.reopen {
		padding: 0;
		background: none;
		border: 0;
		font: inherit;
		font-size: 0.75rem;
		color: var(--muted);
		text-decoration: underline;
		cursor: pointer;
		opacity: 0.7;
	}
	.reopen:hover,
	.reopen:focus-visible {
		opacity: 1;
		color: var(--accent);
	}
	.warn {
		margin: 0;
		color: var(--warn);
		font-size: 0.875rem;
	}
</style>
