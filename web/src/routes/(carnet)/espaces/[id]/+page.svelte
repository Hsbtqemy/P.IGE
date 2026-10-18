<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { ApiError } from '#lib/api.js';
	import { v2, type Entry, type Task } from '#lib/api2.js';
	import { onMailFiled, openMail, thunderbird } from '#lib/carnet/thunderbird.svelte.js';
	import { carnet, failure, longDate, reload } from '#lib/carnet/state.svelte.js';

	let id = $derived(page.params.id ?? '');
	let space = $derived(carnet.tree?.spaces.find((s) => s.id === id));
	let tasks = $state<Task[]>([]);
	let entries = $state<Entry[]>([]);
	let loaded = $state(false);
	let loadError = $state('');
	let message = $state('');
	let info = $state('');
	let newTitle = $state('');
	let renaming = $state(false);
	let nameDraft = $state('');

	let isInbox = $derived(space?.name.toLocaleLowerCase('fr') === 'à trier');

	$effect(() => {
		const current = id;
		loaded = false;
		loadError = '';
		message = '';
		info = '';
		void load(current);
	});

	async function load(current = id) {
		try {
			const [t, e] = await Promise.all([v2.spaceTasks(current), v2.timeline({ space_id: current, limit: 200 })]);
			if (current !== id) return;
			tasks = t;
			// The space's own paragraphs: those of its projects are on the project pages.
			entries = e.filter((x) => !x.project_id);
			loaded = true;
		} catch (err) {
			if (current !== id) return;
			loadError = err instanceof ApiError && err.status === 404 ? 'Espace introuvable.' : failure(err, 'Espace non chargé : ');
		}
	}

	onMount(() => onMailFiled(() => void load()));

	async function attempt(what: string, action: () => Promise<unknown>, done?: string) {
		message = '';
		info = '';
		try {
			await action();
			if (done) info = done;
		} catch (err) {
			message = failure(err, `${what} : `);
		}
		await load();
		reload().catch(() => {});
	}

	/** "p:<id>" / "s:<id>" from the « Ranger dans » list. */
	function target(value: string): { project_id?: string; space_id?: string } {
		return value.startsWith('p:') ? { project_id: value.slice(2) } : { space_id: value.slice(2) };
	}

	function placeLabel(value: string): string {
		for (const s of carnet.tree?.spaces ?? []) {
			if (value === `s:${s.id}`) return s.name;
			const p = s.projects.find((x) => value === `p:${x.id}`);
			if (p) return p.name;
		}
		return '';
	}

	function moveTask(task: Task, value: string) {
		if (!value) return;
		void attempt('Tâche non rangée', () => v2.moveTask(task.id, target(value)), `« ${task.title} » rangée dans ${placeLabel(value)}.`);
	}

	function moveEntry(entry: Entry, value: string) {
		if (!value) return;
		void attempt('Paragraphe non rangé', () => v2.moveEntry(entry.id, target(value)), `« ${entry.title || 'Paragraphe'} » rangé dans ${placeLabel(value)}.`);
	}

	function done(task: Task) {
		void attempt('Tâche non terminée', () => v2.updateTask(task.id, { status: 'done' }), `« ${task.title} » terminée.`);
	}

	function removeTask(task: Task) {
		if (!confirm(`Supprimer la tâche « ${task.title} » ?`)) return;
		void attempt('Tâche non supprimée', () => v2.deleteTask(task.id));
	}

	function removeEntry(entry: Entry) {
		if (!confirm(`Supprimer « ${entry.title || entry.body.slice(0, 40)} » du journal ?`)) return;
		void attempt('Paragraphe non supprimé', () => v2.deleteEntry(entry.id));
	}

	function addTask(event: SubmitEvent) {
		event.preventDefault();
		const title = newTitle.trim();
		if (!title) return;
		newTitle = '';
		void attempt('Tâche non créée', () => v2.createTask({ title, space_id: id }));
	}

	function saveName() {
		renaming = false;
		const name = nameDraft.trim();
		if (!space || !name || name === space.name) return;
		void attempt('Nom non modifié', () => v2.renameSpace(id, name));
	}
</script>

{#snippet places(current: string)}
	<option value="">Ranger dans…</option>
	{#each carnet.tree?.spaces ?? [] as s (s.id)}
		<optgroup label={s.name}>
			{#if `s:${s.id}` !== current}<option value="s:{s.id}">{s.name} (sans projet)</option>{/if}
			{#each s.projects as p (p.id)}<option value="p:{p.id}">{p.name}</option>{/each}
		</optgroup>
	{/each}
{/snippet}

<svelte:head><title>{space?.name ?? 'Espace'} · P.IGE</title></svelte:head>

<div class="wrap">
	{#if loadError || (carnet.tree && !space)}
		<p>{loadError || 'Espace introuvable.'}</p>
	{:else if space}
		<header>
			<span class="crumbs">Espace</span>
			{#if renaming}
				<input
					class="name-input"
					bind:value={nameDraft}
					aria-label="Nom de l’espace"
					onblur={saveName}
					onkeydown={(e) => {
						if (e.key === 'Enter') (e.currentTarget as HTMLInputElement).blur();
						if (e.key === 'Escape') renaming = false;
					}}
				/>
			{:else}
				<h1><button class="plain" title="Renommer" onclick={() => ((nameDraft = space?.name ?? ''), (renaming = true))}>{space.name}</button></h1>
			{/if}
			{#if isInbox}
				<p class="hint">Ce qui arrive sans projet (mails classés depuis Thunderbird, notes du téléphone) : à ranger, terminer ou supprimer.</p>
			{/if}
			{#if space.projects.length}
				<nav class="projects" aria-label="Projets de l’espace">
					{#each space.projects as p (p.id)}
						<a href="/projets/{p.id}">{p.name}{#if p.open_tasks}<small>{p.open_tasks}</small>{/if}</a>
					{/each}
				</nav>
			{/if}
		</header>

		{#if message}<p class="message" role="alert">{message}</p>{/if}
		{#if info}<p class="info" role="status">{info}</p>{/if}

		<div class="cols">
			<section aria-labelledby="t-title">
				<h2 id="t-title">Tâches sans projet <small>{tasks.length || ''}</small></h2>
				{#if !loaded}
					<p class="muted">Chargement…</p>
				{:else}
					{#each tasks as task (task.id)}
						<div class="row">
							<input type="checkbox" class="check" onchange={() => done(task)} aria-label="Terminer « {task.title} »" />
							<span class="title">{task.title}</span>
							<span class="tools">
								<select aria-label="Ranger « {task.title} »" onchange={(e) => moveTask(task, (e.currentTarget as HTMLSelectElement).value)}>
									{@render places(`s:${id}`)}
								</select>
								<button class="x" onclick={() => removeTask(task)} aria-label="Supprimer « {task.title} »">×</button>
							</span>
						</div>
					{:else}
						<p class="muted">Aucune tâche.</p>
					{/each}
					<form class="new" onsubmit={addTask}>
						<input bind:value={newTitle} placeholder="+ Nouvelle tâche" aria-label="Nouvelle tâche" />
					</form>
				{/if}
			</section>

			<section aria-labelledby="j-title">
				<h2 id="j-title">Journal de l’espace <small>{entries.length || ''}</small></h2>
				{#if loaded}
					{#each entries as entry (entry.id)}
						<div class="entry">
							<a class="what" href={entry.source === 'writing' ? `/ecrire/${entry.id}` : `/journal/${entry.entry_date}`}>
								<b>{entry.title || entry.body.slice(0, 80)}</b>
								<small>{longDate(entry.entry_date).toLocaleLowerCase('fr')}{entry.mail_message_id ? ' · mail' : ''}{entry.people.length ? ` · ${entry.people.map((p) => p.display_name).join(', ')}` : ''}</small>
							</a>
							<span class="tools">
								{#if entry.mail_message_id && thunderbird.available}
									<button class="btn" onclick={() => entry.mail_message_id && openMail(entry.mail_message_id)}>✉</button>
								{/if}
								<select aria-label="Ranger « {entry.title} »" onchange={(e) => moveEntry(entry, (e.currentTarget as HTMLSelectElement).value)}>
									{@render places(`s:${id}`)}
								</select>
								<button class="x" onclick={() => removeEntry(entry)} aria-label="Supprimer « {entry.title} »">×</button>
							</span>
						</div>
					{:else}
						<p class="muted">Rien d’écrit hors des projets.</p>
					{/each}
				{/if}
			</section>
		</div>
	{:else}
		<p>Chargement…</p>
	{/if}
</div>

<style>
	.wrap {
		padding: 22px 32px 48px;
		display: flex;
		flex-direction: column;
		gap: 14px;
	}
	header {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.crumbs,
	.muted,
	small,
	.hint {
		font-size: 0.875rem;
		color: var(--muted);
	}
	.hint {
		margin: 0;
	}
	h1 {
		font-size: 1.875rem;
		margin: 0;
	}
	.plain {
		padding: 0;
		font: inherit;
		color: inherit;
		background: none;
		border: 0;
		cursor: pointer;
	}
	.name-input {
		font-family: var(--serif);
		font-size: 1.875rem;
		font-weight: 600;
		color: var(--ink);
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 6px;
		padding: 0 6px;
		max-width: 100%;
	}
	.projects {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.projects a {
		display: inline-flex;
		gap: 6px;
		align-items: baseline;
		padding: 2px 10px;
		font-size: 0.875rem;
		text-decoration: none;
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 12px;
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
		grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
		gap: 28px;
		align-items: start;
	}
	h2 {
		font-size: 1.125rem;
		margin: 0 0 4px;
		padding-bottom: 4px;
		border-bottom: var(--rule);
	}
	h2 small {
		font-family: var(--sans);
		font-weight: 400;
	}
	.row,
	.entry {
		display: flex;
		flex-wrap: wrap;
		gap: 6px 10px;
		align-items: center;
		padding: 8px 0;
		border-bottom: 1px solid var(--line);
	}
	.check {
		width: 16px;
		height: 16px;
		accent-color: var(--accent);
	}
	.title {
		flex: 1 1 180px;
		font-weight: 700;
		min-width: 0;
		overflow-wrap: anywhere;
	}
	.what {
		flex: 1 1 200px;
		display: flex;
		flex-direction: column;
		min-width: 0;
		text-decoration: none;
	}
	.what b {
		font-family: var(--serif);
		overflow-wrap: anywhere;
	}
	.tools {
		display: flex;
		gap: 4px;
		align-items: center;
		margin-left: auto;
	}
	select,
	input {
		font: inherit;
		font-size: 0.875rem;
		color: var(--ink);
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 6px;
		padding: 3px 6px;
		max-width: 190px;
	}
	.x {
		width: 28px;
		height: 28px;
		font-size: 1.1rem;
		color: var(--muted);
		background: none;
		border: 0;
		border-radius: 6px;
		cursor: pointer;
	}
	.x:hover {
		background: var(--soft);
		color: var(--warn);
	}
	.new input {
		width: 100%;
		max-width: none;
		box-sizing: border-box;
		margin-top: 8px;
		padding: 8px 10px;
		background: transparent;
		border-style: dashed;
	}
	@media (max-width: 900px) {
		.cols {
			grid-template-columns: 1fr;
		}
	}
	@media (max-width: 600px) {
		.wrap {
			padding: 16px;
		}
	}
</style>
