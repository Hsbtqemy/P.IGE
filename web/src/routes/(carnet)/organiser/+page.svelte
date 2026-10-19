<script lang="ts">
	import { tick } from 'svelte';
	import { ApiError } from '#lib/api.js';
	import { v2, type Project, type Tree } from '#lib/api2.js';
	import { failure, reload } from '#lib/carnet/state.svelte.js';

	let tree = $state<Tree | null>(null);
	let showAll = $state(false);
	let message = $state('');
	let info = $state('');
	let busy = $state(false);
	let renaming = $state<string | null>(null); // "s:<id>" or "p:<id>"
	let nameDraft = $state('');
	let newSpace = $state('');
	let newProject = $state<Record<string, string>>({});

	const STATES: Record<Project['state'], string> = { active: 'Actif', dormant: 'En sommeil', closed: 'Clos' };

	async function load() {
		try {
			tree = await v2.tree(showAll);
		} catch (err) {
			message = failure(err, 'Organisation non chargée : ');
		}
	}

	$effect(() => {
		void showAll;
		void load();
	});

	/** Run a change, then reload this page and the side column. */
	async function run(what: string, action: () => Promise<unknown>, done?: string) {
		message = '';
		info = '';
		busy = true;
		try {
			await action();
			if (done) info = done;
		} catch (err) {
			if (err instanceof ApiError && err.status === 409) {
				message = `${what} : il reste des tâches, des notes ou du temps dedans. Déplace-les ou supprime-les d’abord, ou archive plutôt.`;
			} else {
				message = failure(err, `${what} : `);
			}
		} finally {
			busy = false;
			await load();
			reload().catch(() => {});
		}
	}

	// ------------------------------------------------------------ names

	async function startRename(key: string, current: string) {
		renaming = key;
		nameDraft = current;
		await tick();
		document.getElementById('rename-input')?.focus();
	}

	function saveRename() {
		const key = renaming;
		renaming = null;
		const name = nameDraft.trim();
		if (!key || !name) return;
		const id = key.slice(2);
		if (key.startsWith('s:')) void run('Nom non modifié', () => v2.updateSpace(id, { name }));
		else void run('Nom non modifié', () => v2.updateProject(id, { name }));
	}

	function renameKeys(event: KeyboardEvent) {
		if (event.key === 'Enter') (event.currentTarget as HTMLInputElement).blur();
		if (event.key === 'Escape') renaming = null;
	}

	// ------------------------------------------------------------ spaces

	function addSpace(event: SubmitEvent) {
		event.preventDefault();
		const name = newSpace.trim();
		if (!name) return;
		newSpace = '';
		void run('Espace non créé', () => v2.createSpace(name), `Espace « ${name} » créé.`);
	}

	function moveSpace(index: number, delta: number) {
		const spaces = tree?.spaces ?? [];
		const target = spaces[index + delta];
		if (!target) return;
		const id = spaces[index].id;
		void run('Ordre non modifié', () => v2.placeSpace(id, delta < 0 ? { before: target.id } : { after: target.id }));
	}

	function archiveSpace(id: string, name: string, archived: boolean) {
		void run(
			'Espace non modifié',
			() => v2.updateSpace(id, { archived: !archived }),
			archived ? `« ${name} » est de retour dans la colonne.` : `« ${name} » archivé : il n’apparaît plus dans la colonne, rien n’est perdu.`
		);
	}

	function deleteSpace(id: string, name: string) {
		if (!confirm(`Supprimer l’espace « ${name} » ? Seul un espace vide peut l’être.`)) return;
		void run('Espace non supprimé', () => v2.deleteSpace(id), `Espace « ${name} » supprimé.`);
	}

	// ------------------------------------------------------------ projects

	function addProject(event: SubmitEvent, spaceId: string, parentId: string | null = null) {
		event.preventDefault();
		const key = parentId ?? spaceId;
		const name = (newProject[key] ?? '').trim();
		if (!name) return;
		newProject[key] = '';
		void run(
			'Projet non créé',
			() => v2.createProject({ space_id: spaceId, name, parent_id: parentId }),
			`${parentId ? 'Sous-projet' : 'Projet'} « ${name} » créé.`
		);
	}

	function siblings(project: Project): Project[] {
		const space = tree?.spaces.find((s) => s.id === project.space_id);
		return (space?.projects ?? []).filter((p) => p.parent_id === project.parent_id);
	}

	function moveProjectBy(project: Project, delta: number) {
		const list = siblings(project);
		const i = list.findIndex((p) => p.id === project.id);
		const target = list[i + delta];
		if (!target) return;
		void run('Ordre non modifié', () => v2.placeProject(project.id, delta < 0 ? { before: target.id } : { after: target.id }));
	}

	/** "s:<space>" (top level of a space) or "p:<project>" (sub-project of it). */
	function moveProjectTo(project: Project, value: string) {
		if (!value) return;
		let to: { space_id: string; parent_id: string | null };
		let where: string;
		if (value.startsWith('s:')) {
			const space = tree?.spaces.find((s) => s.id === value.slice(2));
			to = { space_id: value.slice(2), parent_id: null };
			where = `l’espace « ${space?.name ?? ''} »`;
		} else {
			const parent = tree?.spaces.flatMap((s) => s.projects).find((p) => p.id === value.slice(2));
			if (!parent) return;
			to = { space_id: parent.space_id, parent_id: parent.id };
			where = `« ${parent.name} », comme sous-projet`;
		}
		void run('Projet non déplacé', () => v2.moveProject(project.id, to), `« ${project.name} » déplacé dans ${where}. Ses tâches, notes et temps suivent.`);
	}

	function hasChildren(project: Project): boolean {
		return (tree?.spaces ?? []).some((s) => s.projects.some((p) => p.parent_id === project.id));
	}

	function deleteProject(project: Project) {
		if (!confirm(`Supprimer le projet « ${project.name} » ? Seul un projet vide peut l’être ; sinon, passe-le en « Clos ».`)) return;
		void run('Projet non supprimé', () => v2.deleteProject(project.id), `Projet « ${project.name} » supprimé.`);
	}

	/** Projects of a space in display order: each top-level one followed by its sub-projects. */
	function ordered(projects: Project[]): Project[] {
		const top = projects.filter((p) => !p.parent_id);
		return top.flatMap((p) => [p, ...projects.filter((c) => c.parent_id === p.id)]);
	}
</script>

<svelte:head><title>Organiser · P.IGE</title></svelte:head>

<div class="wrap">
	<header>
		<h1>Organiser</h1>
		<p class="hint">
			Les espaces sont les grandes structures (laboratoires, services, perso) ; les projets y vivent, avec au plus un niveau
			de sous-projet. Déplacer un projet emporte ses tâches, ses notes et son temps.
		</p>
		<label class="toggle"><input type="checkbox" bind:checked={showAll} /> Afficher les espaces archivés et les projets clos</label>
	</header>

	{#if message}<p class="message" role="alert">{message}</p>{/if}
	{#if info}<p class="info" role="status">{info}</p>{/if}

	{#if !tree}
		<p class="muted">Chargement…</p>
	{:else}
		{#each tree.spaces as space, si (space.id)}
			<section class="space" class:archived={space.archived} aria-label={space.name}>
				<div class="space-head">
					{#if renaming === `s:${space.id}`}
						<input id="rename-input" class="rename" bind:value={nameDraft} onblur={saveRename} onkeydown={renameKeys} aria-label="Nom de l’espace" />
					{:else}
						<h2>
							<button class="plain" onclick={() => startRename(`s:${space.id}`, space.name)} title="Renommer">{space.name}</button>
							{#if space.archived}<small>archivé</small>{/if}
						</h2>
					{/if}
					<span class="tools">
						<button class="icon" onclick={() => moveSpace(si, -1)} disabled={busy || si === 0} aria-label="Monter « {space.name} »">↑</button>
						<button class="icon" onclick={() => moveSpace(si, 1)} disabled={busy || si === tree.spaces.length - 1} aria-label="Descendre « {space.name} »">↓</button>
						<button class="btn" onclick={() => archiveSpace(space.id, space.name, space.archived)} disabled={busy}>{space.archived ? 'Désarchiver' : 'Archiver'}</button>
						<button class="btn danger" onclick={() => deleteSpace(space.id, space.name)} disabled={busy}>Supprimer</button>
					</span>
				</div>

				<ul class="projects">
					{#each ordered(space.projects) as project (project.id)}
						<li class:sub={project.parent_id} class:closed={project.state !== 'active'}>
							{#if renaming === `p:${project.id}`}
								<input id="rename-input" class="rename" bind:value={nameDraft} onblur={saveRename} onkeydown={renameKeys} aria-label="Nom du projet" />
							{:else}
								<span class="pname">
									<button class="plain" onclick={() => startRename(`p:${project.id}`, project.name)} title="Renommer">{project.name}</button>
									<a class="open" href="/projets/{project.id}" aria-label="Ouvrir « {project.name} »">↗</a>
									{#if project.open_tasks}<small>{project.open_tasks} tâche{project.open_tasks > 1 ? 's' : ''}</small>{/if}
								</span>
							{/if}
							<span class="tools">
								<button class="icon" onclick={() => moveProjectBy(project, -1)} disabled={busy} aria-label="Monter « {project.name} »">↑</button>
								<button class="icon" onclick={() => moveProjectBy(project, 1)} disabled={busy} aria-label="Descendre « {project.name} »">↓</button>
								<select
									value={project.state}
									onchange={(e) => run('État non modifié', () => v2.updateProject(project.id, { state: (e.currentTarget as HTMLSelectElement).value as Project['state'] }))}
									aria-label="État de « {project.name} »"
								>
									{#each Object.entries(STATES) as [value, label] (value)}<option {value}>{label}</option>{/each}
								</select>
								<select
									value={project.team ?? ''}
									onchange={(e) => run('Équipe non modifiée', () => v2.updateProject(project.id, { team: (e.currentTarget as HTMLSelectElement).value || null }))}
									aria-label="Équipe de « {project.name} »"
								>
									<option value="">Équipe —</option>
									<option value="A">Équipe A</option>
									<option value="B">Équipe B</option>
								</select>
								<select
									value=""
									onchange={(e) => moveProjectTo(project, (e.currentTarget as HTMLSelectElement).value)}
									aria-label="Déplacer « {project.name} »"
								>
									<option value="">Déplacer…</option>
									{#each tree.spaces as target (target.id)}
										<optgroup label={target.name}>
											{#if !(target.id === project.space_id && !project.parent_id)}
												<option value="s:{target.id}">{target.id === project.space_id ? 'Remonter au premier niveau' : `Dans « ${target.name} »`}</option>
											{/if}
											{#if !hasChildren(project)}
												{#each target.projects.filter((p) => !p.parent_id && p.id !== project.id && p.id !== project.parent_id) as parent (parent.id)}
													<option value="p:{parent.id}">Sous-projet de « {parent.name} »</option>
												{/each}
											{/if}
										</optgroup>
									{/each}
								</select>
								<button class="icon danger" onclick={() => deleteProject(project)} disabled={busy} aria-label="Supprimer « {project.name} »">×</button>
							</span>
						</li>
					{:else}
						<li class="muted">Aucun projet.</li>
					{/each}
				</ul>

				<form class="add" onsubmit={(e) => addProject(e, space.id)}>
					<input bind:value={newProject[space.id]} placeholder="+ Nouveau projet dans « {space.name} »" aria-label="Nouveau projet dans « {space.name} »" />
					{#if space.projects.some((p) => !p.parent_id)}
						<select
							aria-label="Ou comme sous-projet de"
							onchange={(e) => {
								const parent = (e.currentTarget as HTMLSelectElement).value;
								(e.currentTarget as HTMLSelectElement).value = '';
								if (!parent) return;
								const name = (newProject[space.id] ?? '').trim();
								if (!name) {
									message = 'Écris d’abord le nom du sous-projet.';
									return;
								}
								newProject[space.id] = '';
								void run('Sous-projet non créé', () => v2.createProject({ space_id: space.id, name, parent_id: parent }), `Sous-projet « ${name} » créé.`);
							}}
						>
							<option value="">… ou comme sous-projet de</option>
							{#each space.projects.filter((p) => !p.parent_id) as parent (parent.id)}<option value={parent.id}>{parent.name}</option>{/each}
						</select>
					{/if}
				</form>
			</section>
		{/each}

		<form class="add new-space" onsubmit={addSpace}>
			<input bind:value={newSpace} placeholder="+ Nouvel espace" aria-label="Nouvel espace" />
			<button class="btn" disabled={!newSpace.trim() || busy}>Créer l’espace</button>
		</form>
	{/if}
</div>

<style>
	.wrap {
		padding: 22px 32px 48px;
		display: flex;
		flex-direction: column;
		gap: 16px;
		max-width: 980px;
	}
	header {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	h1 {
		font-size: 1.875rem;
		margin: 0;
	}
	.hint,
	.muted,
	small {
		font-size: 0.875rem;
		color: var(--muted);
		font-weight: 400;
	}
	.hint {
		margin: 0;
		max-width: 70ch;
	}
	.toggle {
		display: flex;
		gap: 6px;
		align-items: center;
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
	.space {
		display: flex;
		flex-direction: column;
		gap: 6px;
		padding: 12px 14px;
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 10px;
	}
	.space.archived {
		opacity: 0.7;
	}
	.space-head {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		align-items: center;
		justify-content: space-between;
		padding-bottom: 6px;
		border-bottom: var(--rule);
	}
	h2 {
		margin: 0;
		font-size: 1.25rem;
	}
	.plain {
		padding: 0;
		font: inherit;
		color: inherit;
		text-align: left;
		background: none;
		border: 0;
		cursor: text;
	}
	.plain:hover {
		text-decoration: underline dotted var(--muted);
		text-underline-offset: 4px;
	}
	.rename {
		font: inherit;
		font-weight: 700;
		color: var(--ink);
		background: var(--surface);
		border: 1px solid var(--accent);
		border-radius: 6px;
		padding: 2px 6px;
		min-width: 0;
	}
	.tools {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
		align-items: center;
	}
	.icon {
		width: 30px;
		height: 30px;
		font: inherit;
		color: var(--muted);
		background: transparent;
		border: 1px solid var(--line);
		border-radius: 6px;
		cursor: pointer;
	}
	.icon:disabled {
		opacity: 0.35;
		cursor: default;
	}
	.danger {
		color: var(--warn);
	}
	select {
		max-width: 210px;
		font: inherit;
		font-size: 0.8125rem;
		color: var(--ink);
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 6px;
		padding: 4px 4px;
	}
	.projects {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.projects li {
		display: flex;
		flex-wrap: wrap;
		gap: 6px 12px;
		align-items: center;
		justify-content: space-between;
		padding: 6px 0;
		border-bottom: 1px solid var(--line);
	}
	.projects li.sub {
		padding-left: 24px;
	}
	.projects li.sub .pname::before {
		content: '↳ ';
		color: var(--muted);
	}
	.projects li.closed .pname {
		color: var(--muted);
	}
	.pname {
		display: flex;
		gap: 8px;
		align-items: baseline;
		min-width: 0;
		font-weight: 700;
	}
	.open {
		font-size: 0.8125rem;
		color: var(--muted);
		text-decoration: none;
	}
	.add {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.add input {
		flex: 1 1 240px;
		font: inherit;
		color: var(--ink);
		background: transparent;
		border: 1px dashed var(--line);
		border-radius: 6px;
		padding: 6px 10px;
	}
	.add input:focus {
		background: var(--surface);
		border-style: solid;
	}
	.new-space input {
		font-size: 1.0625rem;
	}
	@media (max-width: 600px) {
		.wrap {
			padding: 16px;
		}
	}
</style>
