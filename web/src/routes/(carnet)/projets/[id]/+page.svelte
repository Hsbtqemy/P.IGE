<script lang="ts">
	import { page } from '$app/state';
	import { ApiError } from '#lib/api.js';
	import { v2, type Entry, type ProjectView, type Task } from '#lib/api2.js';
	import { failure, projectOf, spaceOf } from '#lib/carnet/state.svelte.js';

	let id = $derived(page.params.id ?? '');
	let project = $state<ProjectView | null>(null);
	let tasks = $state<Task[]>([]);
	let entries = $state<Entry[]>([]);
	let message = $state('');

	const STATUS: Record<string, string> = { open: 'Ouverte', in_progress: 'En cours', waiting: 'En attente', done: 'Faite' };

	$effect(() => {
		const current = id;
		message = '';
		project = null;
		Promise.all([v2.project(current), v2.projectTasks(current), v2.timeline({ project_id: current, limit: 50 })])
			.then(([p, t, e]) => {
				if (current !== id) return;
				project = p;
				tasks = t;
				entries = e;
			})
			.catch((err) => {
				message = err instanceof ApiError && err.status === 404 ? 'Projet introuvable.' : failure(err, 'Projet non chargé : ');
			});
	});

	function shortDate(iso: string): { day: string; month: string } {
		const d = new Date(`${iso}T12:00:00`);
		return { day: String(d.getDate()), month: d.toLocaleDateString('fr-FR', { month: 'short' }) };
	}
</script>

<svelte:head><title>{project?.name ?? 'Projet'} · P.IGE</title></svelte:head>

<div class="wrap">
	{#if message}
		<p>{message}</p>
	{:else if project}
		<header>
			<span class="crumbs">{spaceOf(project.space_id)?.name}{#if project.parent_id} › {projectOf(project.parent_id)?.name}{/if}</span>
			<h1>{project.name}</h1>
			{#if project.description}<p class="desc">{project.description}</p>{/if}
			{#if project.links.length}
				<div class="links">
					{#each project.links.filter((l) => /^https?:\/\//i.test(l.url)) as link (link.url)}
						<a href={link.url} target="_blank" rel="noopener noreferrer">↗ {link.label ?? link.url.replace(/^https?:\/\//, '')}</a>
					{/each}
				</div>
			{/if}
			<p class="note">Page en lecture pour l’instant : l’ordre des tâches, les étapes et la modification arrivent dans la prochaine étape.</p>
		</header>
		<div class="cols">
			<section>
				<h2>Tâches <small>{tasks.length} {tasks.length > 1 ? 'ouvertes' : 'ouverte'}</small></h2>
				{#each tasks as task, i (task.id)}
					<div class="task">
						<span class="n">{i + 1}</span>
						<span class="title">{task.title}</span>
						<span class="state" class:doing={task.status === 'in_progress'}>{STATUS[task.status]}</span>
						{#if task.steps_total}<small>{task.steps_done}/{task.steps_total}</small>{/if}
					</div>
				{:else}
					<p class="muted">Aucune tâche ouverte.</p>
				{/each}
			</section>
			<section>
				<h2>Journal <small>{entries.length} {entries.length > 1 ? 'entrées' : 'entrée'}</small></h2>
				{#each entries as entry (entry.id)}
					{@const d = shortDate(entry.entry_date)}
					<a class="entry" href="/journal/{entry.entry_date}">
						<span class="date"><b>{d.day}</b><small>{d.month}</small></span>
						<span class="text"><b>{entry.title || entry.body.slice(0, 80)}</b>{#if entry.people.length}<small>{entry.people.map((p) => p.display_name).join(', ')}</small>{/if}</span>
					</a>
				{:else}
					<p class="muted">Rien d’écrit.</p>
				{/each}
			</section>
		</div>
	{:else}
		<p>Chargement…</p>
	{/if}
</div>

<style>
	.wrap {
		padding: 22px 32px;
		display: flex;
		flex-direction: column;
		gap: 16px;
	}
	.crumbs,
	.muted,
	small {
		color: var(--muted);
		font-size: 0.875rem;
	}
	h1 {
		font-size: 1.875rem;
	}
	h2 {
		font-size: 1.125rem;
		padding-bottom: 4px;
		border-bottom: var(--rule);
	}
	h2 small {
		font-family: var(--sans);
		font-weight: 400;
	}
	.desc {
		margin: 4px 0;
		color: var(--muted);
		white-space: pre-line;
	}
	.links {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.links a {
		padding: 2px 9px;
		font-size: 0.8125rem;
		text-decoration: none;
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 12px;
	}
	.note {
		margin: 6px 0 0;
		font-size: 0.8125rem;
		color: var(--muted);
	}
	.cols {
		display: grid;
		grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr);
		gap: 28px;
	}
	.task {
		display: grid;
		grid-template-columns: 24px minmax(0, 1fr) auto auto;
		gap: 8px;
		align-items: baseline;
		padding: 8px 0;
		border-bottom: 1px solid var(--line);
	}
	.n {
		font-family: var(--serif);
		font-weight: 600;
		color: var(--accent);
	}
	.title {
		font-weight: 700;
	}
	.state {
		font-size: 0.8125rem;
		color: var(--muted);
	}
	.state.doing {
		color: var(--accent);
		font-weight: 700;
	}
	.entry {
		display: grid;
		grid-template-columns: 44px minmax(0, 1fr);
		gap: 12px;
		padding: 8px 0;
		border-bottom: 1px solid var(--line);
		text-decoration: none;
	}
	.date {
		display: flex;
		flex-direction: column;
		padding-right: 8px;
		border-right: var(--margin);
		line-height: 1.15;
	}
	.text {
		display: flex;
		flex-direction: column;
		font-family: var(--serif);
	}
	.text small {
		font-family: var(--sans);
	}
	@media (max-width: 900px) {
		.cols {
			grid-template-columns: 1fr;
		}
	}
</style>
