<script lang="ts">
	import { v2, type Task } from '#lib/api2.js';
	import { fold } from '#lib/feuillet.js';
	import { carnet, failure, longDate, reload, shiftDay, todayIso } from '#lib/carnet/state.svelte.js';

	let tasks = $state<Task[] | null>(null);
	let message = $state('');
	let filter = $state<'all' | 'recent' | 'in_progress' | 'waiting' | 'due'>('all');
	let team = $state('');
	let query = $state('');
	let undo = $state<{ task: Task; timer: ReturnType<typeof setTimeout> } | null>(null);

	const LONG = 7; // days: « en cours » or « en attente » for longer than this comes up first

	async function load() {
		try {
			tasks = await v2.openTasks();
		} catch (err) {
			message = failure(err, 'Tâches non chargées : ');
		}
	}

	$effect(() => {
		void load();
	});

	function days(iso: string | undefined): number {
		if (!iso) return 0;
		return Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
	}

	function personName(id: string | null): string {
		return carnet.people.find((p) => p.id === id)?.display_name ?? 'quelqu’un';
	}

	function shortDay(iso: string): string {
		return new Date(`${iso}T12:00:00`).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' });
	}

	let projectTeam = $derived(
		new Map((carnet.tree?.spaces ?? []).flatMap((s) => s.projects).map((p) => [p.id, p.team ?? '']))
	);
	let teams = $derived([...new Set([...projectTeam.values()].filter(Boolean))].sort());

	let shown = $derived.by(() => {
		const words = fold(query).split(' ').filter(Boolean);
		return (tasks ?? []).filter((t) => {
			if (filter === 'in_progress' && t.status !== 'in_progress') return false;
			if (filter === 'waiting' && t.status !== 'waiting') return false;
			if (filter === 'due' && !t.due_date) return false;
			if (team && (!t.project_id || projectTeam.get(t.project_id) !== team)) return false;
			if (words.length) {
				const hay = fold(t.title);
				if (!words.every((w) => hay.includes(w))) return false;
			}
			return true;
		});
	});

	/** Long in progress, long waited for, or overdue: shown first. */
	let watch = $derived(
		shown
			.filter(
				(t) =>
					(t.status === 'in_progress' && days(t.status_since) >= LONG) ||
					(t.status === 'waiting' && days(t.status_since) >= LONG) ||
					(t.due_date && t.due_date < todayIso())
			)
			.sort((a, b) => (a.status_since ?? '').localeCompare(b.status_since ?? ''))
	);

	/** « Récentes »: the last added first, by day of creation, whatever the project. */
	const RECENT_MAX = 60;
	let recentBlocks = $derived.by(() => {
		const local = (iso: string) => {
			const d = new Date(iso);
			return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
		};
		const today = todayIso();
		const yesterday = shiftDay(today, -1);
		const sorted = shown
			.filter((t) => t.created_at)
			.sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? ''))
			.slice(0, RECENT_MAX);
		const blocks: { key: string; title: string; tasks: Task[] }[] = [];
		for (const t of sorted) {
			const day = local(t.created_at!);
			const title = day === today ? 'Ajoutées aujourd’hui' : day === yesterday ? 'Hier' : longDate(day);
			const last = blocks.at(-1);
			if (last?.key === day) last.tasks.push(t);
			else blocks.push({ key: day, title, tasks: [t] });
		}
		return blocks;
	});

	/** « Par échéance »: one list by date, in blocks, whatever the project. */
	let dueBlocks = $derived.by(() => {
		const today = todayIso();
		const tomorrow = shiftDay(today, 1);
		const week = shiftDay(today, 7);
		const dated = shown.filter((t) => t.due_date).sort((a, b) => (a.due_date ?? '').localeCompare(b.due_date ?? ''));
		const blocks = [
			{ key: 'late', title: 'En retard', tasks: dated.filter((t) => t.due_date! < today).reverse() },
			{ key: 'today', title: 'Aujourd’hui', tasks: dated.filter((t) => t.due_date === today) },
			{ key: 'tomorrow', title: 'Demain', tasks: dated.filter((t) => t.due_date === tomorrow) },
			{ key: 'week', title: 'Dans les 7 jours', tasks: dated.filter((t) => t.due_date! > tomorrow && t.due_date! <= week) },
			{ key: 'later', title: 'Plus tard', tasks: dated.filter((t) => t.due_date! > week) }
		];
		return blocks.filter((b) => b.tasks.length);
	});

	interface Group {
		key: string;
		title: string;
		href: string;
		space: string;
		team: string;
		tasks: Task[];
	}

	let groups = $derived.by((): Group[] => {
		const out: Group[] = [];
		for (const space of carnet.tree?.spaces ?? []) {
			const own = shown.filter((t) => !t.project_id && t.space_id === space.id);
			if (own.length) out.push({ key: `s:${space.id}`, title: `${space.name} (sans projet)`, href: `/espaces/${space.id}`, space: space.name, team: '', tasks: own });
			for (const project of space.projects) {
				const mine = shown.filter((t) => t.project_id === project.id);
				if (mine.length) out.push({ key: `p:${project.id}`, title: project.name, href: `/projets/${project.id}`, space: space.name, team: project.team ?? '', tasks: mine });
			}
		}
		// Tasks of closed projects or archived spaces still open somewhere: never hidden.
		const placed = new Set(out.flatMap((g) => g.tasks.map((t) => t.id)));
		const rest = shown.filter((t) => !placed.has(t.id));
		if (rest.length) out.push({ key: 'rest', title: 'Projets clos ou archivés', href: '', space: '', team: '', tasks: rest });
		return out;
	});

	async function done(task: Task) {
		message = '';
		try {
			await v2.updateTask(task.id, { status: 'done' });
			tasks = (tasks ?? []).filter((t) => t.id !== task.id);
			if (undo) clearTimeout(undo.timer);
			undo = { task, timer: setTimeout(() => (undo = null), 8000) };
			reload().catch(() => {});
		} catch (err) {
			message = failure(err, 'Tâche non terminée : ');
		}
	}

	async function undoDone() {
		if (!undo) return;
		const { task, timer } = undo;
		clearTimeout(timer);
		undo = null;
		try {
			await v2.updateTask(
				task.id,
				task.status === 'waiting' && task.waiting_on ? { status: 'waiting', waiting_on: task.waiting_on } : { status: task.status }
			);
			await load();
			reload().catch(() => {});
		} catch (err) {
			message = failure(err, 'Annulation impossible : ');
		}
	}

	const FILTERS: { value: typeof filter; label: string }[] = [
		{ value: 'all', label: 'Toutes' },
		{ value: 'recent', label: 'Récentes' },
		{ value: 'in_progress', label: 'En cours' },
		{ value: 'waiting', label: 'En attente' },
		{ value: 'due', label: 'Par échéance' }
	];
</script>

{#snippet row(task: Task, showPlace: boolean)}
	{@const late = task.due_date && task.due_date < todayIso()}
	<li>
		<input type="checkbox" class="check" onchange={() => done(task)} aria-label="Terminer « {task.title} »" />
		<a class="title" href="{task.project_id ? `/projets/${task.project_id}` : `/espaces/${task.space_id}`}?tache={task.id}">{task.title}</a>
		<span class="info">
			{#if showPlace}<span>{carnet.tree?.spaces.flatMap((s) => s.projects).find((p) => p.id === task.project_id)?.name ?? carnet.tree?.spaces.find((s) => s.id === task.space_id)?.name ?? ''}</span>{/if}
			{#if task.status === 'in_progress'}<span class="doing" class:long={days(task.status_since) >= LONG}>en cours{days(task.status_since) >= 1 ? ` depuis ${days(task.status_since)} j` : ''}</span>{/if}
			{#if task.status === 'waiting'}<span class="waiting">attend {personName(task.waiting_on)}{days(task.status_since) >= 1 ? ` depuis ${days(task.status_since)} j` : ''}</span>{/if}
			{#if task.due_date}<span class:late>pour le {shortDay(task.due_date)}</span>{/if}
			{#if task.steps_total}<span>{task.steps_done}/{task.steps_total}</span>{/if}
		</span>
	</li>
{/snippet}

<svelte:head><title>Tâches · P.IGE</title></svelte:head>

<div class="wrap">
	<header>
		<h1>Tâches <small>{tasks ? `${tasks.length} ouvertes` : ''}</small></h1>
		<div class="tools">
			<div class="chips" role="group" aria-label="Filtrer">
				{#each FILTERS as f (f.value)}
					<button class="chip" class:on={filter === f.value} aria-pressed={filter === f.value} onclick={() => (filter = f.value)}>{f.label}</button>
				{/each}
				{#each teams as t (t)}
					<button class="chip" class:on={team === t} aria-pressed={team === t} onclick={() => (team = team === t ? '' : t)}>Équipe {t}</button>
				{/each}
			</div>
			<input type="search" bind:value={query} placeholder="Chercher une tâche" aria-label="Chercher une tâche" />
		</div>
	</header>

	{#if message}<p class="message" role="alert">{message}</p>{/if}
	{#if undo}
		<p class="undo" role="status">« {undo.task.title} » terminée. <button class="link" onclick={undoDone}>Annuler</button></p>
	{/if}

	{#if !tasks}
		<p class="muted">Chargement…</p>
	{:else}
		{#if filter === 'recent'}
			{#each recentBlocks as b (b.key)}
				<section aria-label={b.title}>
					<h2>{b.title} <small>{b.tasks.length}</small></h2>
					<ul>
						{#each b.tasks as task (task.id)}{@render row(task, true)}{/each}
					</ul>
				</section>
			{:else}
				<p class="muted">Aucune tâche ne correspond.</p>
			{/each}
			{#if shown.length > RECENT_MAX}<p class="muted">Les {RECENT_MAX} dernières ajoutées ; la recherche trouve les autres.</p>{/if}
		{:else if filter === 'due'}
			{#each dueBlocks as b (b.key)}
				<section class:watch={b.key === 'late'} aria-label={b.title}>
					<h2>{b.title} <small>{b.tasks.length}</small></h2>
					<ul>
						{#each b.tasks as task (task.id)}{@render row(task, true)}{/each}
					</ul>
				</section>
			{:else}
				<p class="muted">Aucune tâche avec une échéance.</p>
			{/each}
		{:else}
		{#if watch.length}
			<section class="watch" aria-labelledby="w-title">
				<h2 id="w-title">À surveiller <small>en cours ou en attente depuis plus d’une semaine, échéance passée</small></h2>
				<ul>
					{#each watch as task (task.id)}{@render row(task, true)}{/each}
				</ul>
			</section>
		{/if}

		{#each groups as g (g.key)}
			<section aria-label={g.title}>
				<h2>
					{#if g.href}<a href={g.href}>{g.title}</a>{:else}{g.title}{/if}
					{#if g.team}<span class="team">{g.team}</span>{/if}
					<small>{g.space && !g.title.startsWith(g.space) ? `${g.space} · ` : ''}{g.tasks.length}</small>
				</h2>
				<ul>
					{#each g.tasks as task (task.id)}{@render row(task, false)}{/each}
				</ul>
			</section>
		{:else}
			<p class="muted">Aucune tâche ne correspond.</p>
		{/each}
		{/if}
	{/if}
</div>

<style>
	.wrap {
		padding: 22px 32px 48px;
		display: flex;
		flex-direction: column;
		gap: 18px;
		max-width: 920px;
	}
	header {
		display: flex;
		flex-direction: column;
		gap: 10px;
	}
	h1 {
		font-size: 1.875rem;
		margin: 0;
	}
	small,
	.muted {
		font-family: var(--sans);
		font-weight: 400;
		font-size: 0.875rem;
		color: var(--muted);
	}
	.tools {
		display: flex;
		flex-wrap: wrap;
		gap: 10px;
		align-items: center;
		justify-content: space-between;
	}
	.chips {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.chip {
		min-height: 30px;
		padding: 0 12px;
		font: inherit;
		font-size: 0.8125rem;
		color: var(--ink);
		background: transparent;
		border: 1px solid var(--line);
		border-radius: 15px;
		cursor: pointer;
	}
	.chip.on {
		font-weight: 700;
		background: var(--soft);
		border-color: var(--accent);
	}
	input[type='search'] {
		flex: 0 1 260px;
		font: inherit;
		color: var(--ink);
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 6px;
		padding: 6px 10px;
		min-width: 0;
	}
	.message {
		margin: 0;
		padding: 8px 12px;
		color: var(--warn);
		background: var(--warn-soft);
		border-radius: 8px;
	}
	.undo {
		margin: 0;
		font-size: 0.875rem;
	}
	.link {
		font: inherit;
		color: var(--accent);
		text-decoration: underline;
		background: none;
		border: 0;
		cursor: pointer;
	}
	h2 {
		display: flex;
		align-items: baseline;
		flex-wrap: wrap;
		gap: 8px;
		margin: 0 0 4px;
		padding-bottom: 4px;
		font-size: 1.125rem;
		border-bottom: var(--rule);
	}
	h2 a {
		text-decoration: none;
	}
	h2 a:hover {
		text-decoration: underline;
	}
	.team {
		font-family: var(--sans);
		font-size: 0.6875rem;
		font-weight: 700;
		color: var(--muted);
		border: 1px solid var(--line);
		border-radius: 4px;
		padding: 0 4px;
	}
	.watch {
		padding: 12px 14px;
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 10px;
	}
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	li {
		display: grid;
		grid-template-columns: 20px minmax(0, 1fr) auto;
		gap: 8px;
		align-items: baseline;
		padding: 7px 0;
		border-bottom: 1px solid var(--line);
	}
	li:last-child {
		border-bottom: 0;
	}
	.check {
		width: 16px;
		height: 16px;
		accent-color: var(--accent);
		align-self: center;
	}
	.title {
		font-weight: 700;
		text-decoration: none;
		overflow-wrap: anywhere;
	}
	.title:hover {
		text-decoration: underline;
	}
	.info {
		display: flex;
		flex-wrap: wrap;
		justify-content: flex-end;
		gap: 8px;
		font-size: 0.8125rem;
		color: var(--muted);
	}
	.doing {
		color: var(--accent);
	}
	.doing.long,
	.waiting,
	.late {
		color: var(--warn);
		font-weight: 700;
	}
	@media (max-width: 600px) {
		.wrap {
			padding: 16px;
		}
		li {
			grid-template-columns: 20px minmax(0, 1fr);
		}
		.info {
			grid-column: 2;
			justify-content: flex-start;
		}
	}
</style>
