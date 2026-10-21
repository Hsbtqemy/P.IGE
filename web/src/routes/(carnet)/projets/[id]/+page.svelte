<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { page } from '$app/state';
	import { ApiError } from '#lib/api.js';
	import { v2, type Entry, type Place, type ProjectView, type Task, type TaskStatus, type TaskView } from '#lib/api2.js';
	import { onMailFiled } from '#lib/carnet/thunderbird.svelte.js';
	import TaskOrigin from '#lib/carnet/TaskOrigin.svelte';
	import PersonPicker from '#lib/carnet/PersonPicker.svelte';
	import ProjectPeople from '#lib/carnet/ProjectPeople.svelte';
	import { carnet, failure, isDay, projectOf, reload, spaceOf, todayIso } from '#lib/carnet/state.svelte.js';

	let id = $derived(page.params.id ?? '');
	let project = $state<ProjectView | null>(null);
	let tasks = $state<Task[]>([]);
	let done = $state<Task[] | null>(null); // null: not shown
	let entries = $state<Entry[]>([]);
	let loadError = $state('');
	let message = $state('');

	// Header editing
	let editingName = $state(false);
	let nameDraft = $state('');
	let editingDesc = $state(false);
	let descDraft = $state('');

	// New task
	let newTitle = $state('');
	let adding = $state(false);

	// The task opened for editing
	let openId = $state<string | null>(null);
	let detail = $state<TaskView | null>(null);
	let draft = $state({ title: '', note: '', due: '' });
	let newStep = $state('');
	let waitingOther = $state(false);
	let waitingName = $state('');

	// Last finished task, for « Annuler »
	let undo = $state<{ task: Task; timer: ReturnType<typeof setTimeout> } | null>(null);

	// Drag and drop
	let dragId = $state<string | null>(null);
	let over = $state<{ id: string; after: boolean } | null>(null);

	const STATUS: Record<TaskStatus, string> = { open: 'À faire', in_progress: 'En cours', waiting: 'En attente', done: 'Faite' };
	const ACTIVE: TaskStatus[] = ['open', 'in_progress'];
	const STATE: Record<ProjectView['state'], string> = { active: 'Actif', dormant: 'En sommeil', closed: 'Clos' };

	$effect(() => {
		const current = id;
		loadError = '';
		message = '';
		project = null;
		done = null;
		closeTask();
		Promise.all([v2.project(current), v2.projectTasks(current), v2.timeline({ project_id: current, limit: 50 })])
			.then(([p, t, e]) => {
				if (current !== id) return;
				project = p;
				tasks = t;
				entries = e;
				// /taches and Ma journée link here with ?tache=<id>: open that task right away.
				const wanted = t.find((task) => task.id === page.url.searchParams.get('tache'));
				if (wanted) void openTask(wanted);
			})
			.catch((err) => {
				if (current !== id) return;
				loadError = err instanceof ApiError && err.status === 404 ? 'Projet introuvable.' : failure(err, 'Projet non chargé : ');
			});
	});

	/** Run a write; on failure show why and reload the lists so the page matches the server. */
	async function attempt<T>(what: string, action: () => Promise<T>): Promise<T | undefined> {
		message = '';
		try {
			return await action();
		} catch (err) {
			message = failure(err, `${what} : `);
			if (!(err instanceof ApiError && err.status === 401)) void refreshTasks();
			return undefined;
		}
	}

	async function refreshTasks() {
		const current = id;
		try {
			const [open, all] = await Promise.all([v2.projectTasks(current), done ? v2.projectTasks(current, true) : null]);
			if (current !== id) return;
			tasks = open;
			if (all) done = all.filter((t) => t.status === 'done');
		} catch {
			/* the message already says what failed */
		}
	}

	/** Side column counts follow; never blocks the page. */
	function refreshTree() {
		reload().catch(() => {});
	}

	function shortDate(iso: string): { day: string; month: string } {
		const d = new Date(`${iso}T12:00:00`);
		return { day: String(d.getDate()), month: d.toLocaleDateString('fr-FR', { month: 'short' }) };
	}

	function dueLabel(iso: string): string {
		const d = new Date(`${iso}T12:00:00`);
		return d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' });
	}

	function personName(personId: string | null): string {
		return carnet.people.find((p) => p.id === personId)?.display_name ?? 'quelqu’un';
	}

	// ------------------------------------------------------------ project

	async function startName() {
		if (!project) return;
		nameDraft = project.name;
		editingName = true;
		await tick();
		document.getElementById('project-name')?.focus();
	}

	async function saveName() {
		if (!project || !editingName) return;
		editingName = false;
		const name = nameDraft.trim();
		if (!name || name === project.name) return;
		const saved = await attempt('Nom non enregistré', () => v2.updateProject(project!.id, { name }));
		if (saved) {
			project = saved;
			refreshTree();
		}
	}

	async function startDesc() {
		if (!project) return;
		descDraft = project.description ?? '';
		editingDesc = true;
		await tick();
		document.getElementById('project-desc')?.focus();
	}

	async function saveDesc() {
		if (!project) return;
		editingDesc = false;
		const description = descDraft.trim() || null;
		if (description === (project.description ?? null)) return;
		const saved = await attempt('Description non enregistrée', () => v2.updateProject(project!.id, { description }));
		if (saved) project = saved;
	}

	async function setProject(patch: { team?: string | null; state?: ProjectView['state'] }) {
		if (!project) return;
		const saved = await attempt('Projet non modifié', () => v2.updateProject(project!.id, patch));
		if (saved) {
			project = saved;
			refreshTree();
		}
	}

	// ------------------------------------------------------------ tasks

	async function addTask(event: SubmitEvent) {
		event.preventDefault();
		const title = newTitle.trim();
		if (!title || adding || !project) return;
		adding = true;
		const created = await attempt('Tâche non créée', () => v2.createTask({ title, project_id: project!.id }));
		adding = false;
		if (created) {
			tasks = [...tasks, created];
			newTitle = '';
			refreshTree();
		}
		await tick();
		document.getElementById('new-task')?.focus();
	}

	async function setStatus(task: Task, status: TaskStatus, waitingOn?: string) {
		const previous = { ...task };
		const saved = await attempt('Statut non modifié', () =>
			v2.updateTask(task.id, status === 'waiting' ? { status, waiting_on: waitingOn } : { status })
		);
		if (!saved) return;
		if (status === 'done') {
			tasks = tasks.filter((t) => t.id !== task.id);
			if (done) done = [saved, ...done];
			if (openId === task.id) closeTask();
			if (undo) clearTimeout(undo.timer);
			undo = { task: previous, timer: setTimeout(() => (undo = null), 8000) };
			refreshTree();
		} else if (previous.status === 'done') {
			void refreshTasks();
			refreshTree();
		} else {
			tasks = tasks.map((t) => (t.id === task.id ? saved : t));
			if (detail?.id === task.id) detail = saved;
		}
	}

	async function undoDone() {
		if (!undo) return;
		const { task, timer } = undo;
		clearTimeout(timer);
		undo = null;
		const saved = await attempt('Annulation impossible', () =>
			v2.updateTask(task.id, task.status === 'waiting' && task.waiting_on ? { status: 'waiting', waiting_on: task.waiting_on } : { status: task.status })
		);
		if (saved) {
			void refreshTasks();
			refreshTree();
		}
	}

	async function openTask(task: Task) {
		if (openId === task.id) {
			closeTask();
			return;
		}
		await saveDraft();
		openId = task.id;
		detail = null;
		waitingOther = false;
		newStep = '';
		const loaded = await attempt('Tâche non chargée', () => v2.task(task.id));
		if (!loaded || openId !== task.id) return;
		detail = loaded;
		draft = { title: loaded.title, note: loaded.note ?? '', due: loaded.due_date ?? '' };
		await tick();
		document.getElementById('task-title')?.focus();
	}

	function closeTask() {
		openId = null;
		detail = null;
	}

	/** Title, note and due date are saved when leaving the field. */
	async function saveDraft() {
		if (!detail) return;
		const current = detail;
		const patch: { title?: string; note?: string | null; due_date?: string } = {};
		const title = draft.title.trim();
		if (title && title !== current.title) patch.title = title;
		const note = draft.note.trim();
		if (note !== (current.note ?? '')) patch.note = note || null;
		if (draft.due !== (current.due_date ?? '') && (draft.due === '' || isDay(draft.due))) patch.due_date = draft.due;
		if (!Object.keys(patch).length) return;
		const saved = await attempt('Tâche non enregistrée', () => v2.updateTask(current.id, patch));
		if (!saved) return;
		tasks = tasks.map((t) => (t.id === saved.id ? saved : t));
		if (detail?.id === saved.id) detail = saved;
	}

	/** The people involved in the open task (shown on their page, « Impliqué·e dans »). */
	async function setTaskPeople(ids: string[]) {
		if (!detail) return;
		const id = detail.id;
		const updated = await attempt('Personnes non enregistrées', () => v2.updateTask(id, { person_ids: ids }));
		if (updated && openId === id) detail = updated;
	}

	async function chooseWaiting(value: string) {
		if (!detail) return;
		if (value === '__other') {
			waitingOther = true;
			await tick();
			document.getElementById('waiting-name')?.focus();
			return;
		}
		if (value) await setStatus(detail, 'waiting', value);
	}

	async function waitOnNew(event: SubmitEvent) {
		event.preventDefault();
		const name = waitingName.trim();
		if (!name || !detail) return;
		const person = await attempt('Personne non créée', () => v2.person(name));
		if (!person) return;
		if (!carnet.people.some((p) => p.id === person.id)) carnet.people = [...carnet.people, person];
		waitingOther = false;
		waitingName = '';
		await setStatus(detail, 'waiting', person.id);
	}

	async function removeTask() {
		if (!detail) return;
		const task = detail;
		if (!confirm(`Supprimer la tâche « ${task.title} » et ses étapes ?`)) return;
		const ok = await attempt('Tâche non supprimée', async () => {
			await v2.deleteTask(task.id);
			return true;
		});
		if (!ok) return;
		tasks = tasks.filter((t) => t.id !== task.id);
		closeTask();
		refreshTree();
	}

	async function toggleDone() {
		if (done) {
			done = null;
			return;
		}
		const all = await attempt('Tâches terminées non chargées', () => v2.projectTasks(id, true));
		if (all) done = all.filter((t) => t.status === 'done');
	}

	// ------------------------------------------------------------ order

	async function place(taskId: string, target: string, after: boolean) {
		if (taskId === target) return;
		const item = tasks.find((t) => t.id === taskId);
		if (!item) return;
		const rest = tasks.filter((t) => t.id !== taskId);
		const at = rest.findIndex((t) => t.id === target) + (after ? 1 : 0);
		rest.splice(at, 0, item);
		tasks = rest;
		const where: Place = after ? { after: target } : { before: target };
		await attempt('Ordre non enregistré', () => v2.placeTask(taskId, where));
	}

	async function moveBy(task: Task, delta: number) {
		const i = tasks.findIndex((t) => t.id === task.id);
		const j = i + delta;
		if (i < 0 || j < 0 || j >= tasks.length) return;
		await place(task.id, tasks[j].id, delta > 0);
		await tick();
		document.getElementById(`grip-${task.id}`)?.focus();
	}

	function onGripKey(event: KeyboardEvent, task: Task) {
		if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
			event.preventDefault();
			void moveBy(task, event.key === 'ArrowUp' ? -1 : 1);
		}
	}

	function onDragStart(event: DragEvent, task: Task) {
		dragId = task.id;
		if (event.dataTransfer) {
			event.dataTransfer.effectAllowed = 'move';
			event.dataTransfer.setData('text/plain', task.id);
			const row = (event.currentTarget as HTMLElement).closest('li');
			if (row) event.dataTransfer.setDragImage(row, 16, 16);
		}
	}

	function onDragOver(event: DragEvent, task: Task) {
		if (!dragId || dragId === task.id) return;
		event.preventDefault();
		const box = (event.currentTarget as HTMLElement).getBoundingClientRect();
		over = { id: task.id, after: event.clientY > box.top + box.height / 2 };
	}

	function onDrop(event: DragEvent) {
		event.preventDefault();
		if (dragId && over) void place(dragId, over.id, over.after);
		dragId = null;
		over = null;
	}

	// ------------------------------------------------------------ steps

	async function addStep(event: SubmitEvent) {
		event.preventDefault();
		const label = newStep.trim();
		if (!label || !detail) return;
		const taskId = detail.id;
		const step = await attempt('Étape non ajoutée', () => v2.addStep(taskId, label));
		if (!step || detail?.id !== taskId) return;
		detail.steps = [...detail.steps, step];
		newStep = '';
		syncSteps();
	}

	async function toggleStep(stepId: string, value: boolean) {
		if (!detail) return;
		const step = await attempt('Étape non modifiée', () => v2.updateStep(stepId, value));
		if (!step || !detail) return;
		detail.steps = detail.steps.map((s) => (s.id === stepId ? step : s));
		syncSteps();
	}

	async function removeStep(stepId: string) {
		if (!detail) return;
		const ok = await attempt('Étape non supprimée', async () => {
			await v2.deleteStep(stepId);
			return true;
		});
		if (!ok || !detail) return;
		detail.steps = detail.steps.filter((s) => s.id !== stepId);
		syncSteps();
	}

	async function onStepKey(event: KeyboardEvent, index: number) {
		if (!detail || !event.altKey || (event.key !== 'ArrowUp' && event.key !== 'ArrowDown')) return;
		event.preventDefault();
		const j = index + (event.key === 'ArrowUp' ? -1 : 1);
		if (j < 0 || j >= detail.steps.length) return;
		const steps = [...detail.steps];
		const [step] = steps.splice(index, 1);
		const target = detail.steps[j];
		steps.splice(j, 0, step);
		detail.steps = steps;
		await attempt('Ordre non enregistré', () => v2.placeStep(step.id, j > index ? { after: target.id } : { before: target.id }));
		await tick();
		document.getElementById(`step-${step.id}`)?.focus();
	}

	async function startTaskTimer(taskId: string) {
		const timer = await attempt('Minuteur non démarré', () => v2.startTimer({ task_id: taskId }));
		if (timer) carnet.timers = [...carnet.timers, timer];
	}

	async function stopTaskTimer(taskId: string) {
		for (const timer of carnet.timers.filter((t) => t.task_id === taskId)) {
			const stopped = await attempt('Minuteur non arrêté', () => v2.stopTimer(timer.id));
			if (stopped) carnet.timers = carnet.timers.filter((t) => t.id !== timer.id);
		}
	}

	/** Keep the « 2/5 » of the row in step with the opened task. */
	function syncSteps() {
		if (!detail) return;
		const view = detail;
		const steps_done = view.steps.filter((s) => s.done).length;
		tasks = tasks.map((t) => (t.id === view.id ? { ...t, steps_done, steps_total: view.steps.length } : t));
	}

	// A task created from a mail in Thunderbird shows up at once.
	onMount(() => onMailFiled(() => void refreshTasks()));
</script>

<svelte:head><title>{project?.name ?? 'Projet'} · P.IGE</title></svelte:head>

<div class="wrap">
	{#if loadError}
		<p>{loadError}</p>
	{:else if project}
		<header>
			<span class="crumbs">{spaceOf(project.space_id)?.name}{#if project.parent_id}{' › '}{projectOf(project.parent_id)?.name}{/if}</span>
			{#if editingName}
				<input
					id="project-name"
					class="name-input"
					bind:value={nameDraft}
					aria-label="Nom du projet"
					onblur={saveName}
					onkeydown={(e) => {
						if (e.key === 'Enter') (e.currentTarget as HTMLInputElement).blur();
						if (e.key === 'Escape') editingName = false;
					}}
				/>
			{:else}
				<h1><button class="plain" onclick={startName} title="Renommer">{project.name}</button></h1>
			{/if}
			<div class="meta">
				<label>
					<span>État</span>
					<select value={project.state} onchange={(e) => setProject({ state: (e.currentTarget as HTMLSelectElement).value as ProjectView['state'] })}>
						{#each Object.entries(STATE) as [value, label] (value)}<option {value}>{label}</option>{/each}
					</select>
				</label>
				<label>
					<span>Équipe</span>
					<select value={project.team ?? ''} onchange={(e) => setProject({ team: (e.currentTarget as HTMLSelectElement).value || null })}>
						<option value="">—</option>
						<option value="A">A</option>
						<option value="B">B</option>
						{#if project.team && project.team !== 'A' && project.team !== 'B'}<option value={project.team}>{project.team}</option>{/if}
					</select>
				</label>
			</div>
			<ProjectPeople {project} onchange={(p) => (project = p)} />
			{#if editingDesc}
				<textarea
					id="project-desc"
					class="desc-input"
					bind:value={descDraft}
					rows="3"
					aria-label="Description du projet"
					onblur={saveDesc}
					onkeydown={(e) => {
						if (e.key === 'Escape') editingDesc = false;
					}}
				></textarea>
			{:else if project.description}
				<button class="plain desc" onclick={startDesc} title="Modifier la description">{project.description}</button>
			{:else}
				<button class="plain add-desc" onclick={startDesc}>+ Ajouter une description</button>
			{/if}
			{#if project.links.length}
				<div class="links">
					{#each project.links.filter((l) => /^https?:\/\//i.test(l.url)) as link (link.url)}
						<a href={link.url} target="_blank" rel="noopener noreferrer">↗ {link.label ?? link.url.replace(/^https?:\/\//, '')}</a>
					{/each}
				</div>
			{/if}
		</header>

		{#if message}<p class="message" role="alert">{message}</p>{/if}

		<div class="cols">
			<section aria-labelledby="tasks-title">
				<h2 id="tasks-title">Tâches <small>{tasks.length} {tasks.length > 1 ? 'ouvertes' : 'ouverte'}</small></h2>
				<ol class="tasks">
					{#each tasks as task, i (task.id)}
						{@const late = task.due_date && task.due_date < todayIso()}
						<li
							class:open={openId === task.id}
							class:dragging={dragId === task.id}
							class:drop-before={over?.id === task.id && !over.after}
							class:drop-after={over?.id === task.id && over.after}
							ondragover={(e) => onDragOver(e, task)}
							ondrop={onDrop}
						>
							<div class="row">
								<button
									id="grip-{task.id}"
									class="grip"
									draggable="true"
									ondragstart={(e) => onDragStart(e, task)}
									ondragend={() => {
										dragId = null;
										over = null;
									}}
									onkeydown={(e) => onGripKey(e, task)}
									aria-label="Déplacer « {task.title} » (flèches haut et bas)"
									title="Glisser pour déplacer, ou flèches haut / bas"
								>
									<span class="n">{i + 1}</span>
								</button>
								<input
									type="checkbox"
									class="check"
									checked={false}
									onchange={() => setStatus(task, 'done')}
									aria-label="Terminer « {task.title} »"
								/>
								<button class="plain title" onclick={() => openTask(task)} aria-expanded={openId === task.id}>
									{task.title}
								</button>
								<span class="info">
									{#if task.status === 'in_progress'}<span class="doing">En cours</span>{/if}
									{#if task.status === 'waiting'}<span class="waiting">Attend {personName(task.waiting_on)}</span>{/if}
									{#if task.due_date}<span class:late>pour le {dueLabel(task.due_date)}</span>{/if}
									{#if task.steps_total}<span class="steps">{task.steps_done}/{task.steps_total}</span>{/if}
								</span>
							</div>

							{#if openId === task.id}
								<div class="detail">
									{#if !detail}
										<p class="muted">Chargement…</p>
									{:else}
										<input id="task-title" class="t-title" bind:value={draft.title} onblur={saveDraft} aria-label="Titre de la tâche"
											onkeydown={(e) => e.key === 'Enter' && (e.currentTarget as HTMLInputElement).blur()} />
										<div class="status" role="group" aria-label="Statut">
											{#each ACTIVE as s (s)}
												<button class="seg" class:on={detail.status === s} aria-pressed={detail.status === s} onclick={() => detail && setStatus(detail, s)}>{STATUS[s]}</button>
											{/each}
											<label class="seg" class:on={detail.status === 'waiting'}>
												<span>En attente de</span>
												<select
													value={detail.status === 'waiting' ? (detail.waiting_on ?? '') : ''}
													onchange={(e) => chooseWaiting((e.currentTarget as HTMLSelectElement).value)}
												>
													<option value="">…</option>
													{#each carnet.people as person (person.id)}<option value={person.id}>{person.display_name}</option>{/each}
													<option value="__other">Quelqu’un d’autre…</option>
												</select>
											</label>
										</div>
										{#if waitingOther}
											<form class="inline" onsubmit={waitOnNew}>
												<input id="waiting-name" bind:value={waitingName} placeholder="Nom de la personne" aria-label="Nom de la personne attendue"
													onkeydown={(e) => e.key === 'Escape' && (waitingOther = false)} />
												<button class="btn">Attendre</button>
											</form>
										{/if}
										<label class="field">
											<span>Échéance</span>
											<input type="date" bind:value={draft.due} onchange={saveDraft} />
										</label>
										<div class="field">
											<span>Personnes</span>
											<div class="task-people">
												{#each detail.people as person (person.id)}
													<span class="chip">
														<a href="/personnes/{person.id}">{person.display_name}</a>
														<button class="x" onclick={() => setTaskPeople(detail?.people.filter((p) => p.id !== person.id).map((p) => p.id) ?? [])} aria-label="Retirer {person.display_name} de la tâche">×</button>
													</span>
												{/each}
												<PersonPicker
													id="task-person"
													exclude={detail.people.map((p) => p.id)}
													onpick={(person) => setTaskPeople([...(detail?.people.map((p) => p.id) ?? []), person.id])}
												/>
											</div>
										</div>
										<label class="field">
											<span>Note</span>
											<textarea bind:value={draft.note} rows="3" onblur={saveDraft}></textarea>
										</label>
										<div class="field">
											<span>Étapes {#if detail.steps.length}<small>{detail.steps.filter((s) => s.done).length}/{detail.steps.length}</small>{/if}</span>
											<ul class="steps-list">
												{#each detail.steps as step, si (step.id)}
													<li>
														<input
															id="step-{step.id}"
															type="checkbox"
															checked={step.done}
															onchange={(e) => toggleStep(step.id, (e.currentTarget as HTMLInputElement).checked)}
															onkeydown={(e) => onStepKey(e, si)}
															aria-label="{step.label} (Alt + flèches pour déplacer)"
														/>
														<span class:struck={step.done}>{step.label}</span>
														<button class="x" onclick={() => removeStep(step.id)} aria-label="Supprimer l’étape « {step.label} »">×</button>
													</li>
												{/each}
											</ul>
											<form class="inline" onsubmit={addStep}>
												<input bind:value={newStep} placeholder="Nouvelle étape" aria-label="Nouvelle étape" />
											</form>
										</div>
										{#if detail.origin_entry_id}<TaskOrigin entryId={detail.origin_entry_id} />{/if}
										<div class="actions">
											<button class="btn" onclick={closeTask}>Fermer</button>
											{#if carnet.timers.some((t) => t.task_id === detail?.id)}
												<button class="btn" onclick={() => detail && stopTaskTimer(detail.id)}>■ Arrêter le minuteur</button>
											{:else}
												<button class="btn" onclick={() => detail && startTaskTimer(detail.id)}>▶ Démarrer un minuteur</button>
											{/if}
											<button class="btn danger" onclick={removeTask}>Supprimer la tâche</button>
										</div>
									{/if}
								</div>
							{/if}
						</li>
					{:else}
						<li class="empty muted">Aucune tâche ouverte.</li>
					{/each}
				</ol>
				<form class="new" onsubmit={addTask}>
					<input id="new-task" bind:value={newTitle} placeholder="+ Nouvelle tâche" aria-label="Nouvelle tâche" aria-busy={adding} />
				</form>
				{#if undo}
					<p class="undo" role="status">
						« {undo.task.title} » terminée.
						<button class="plain link" onclick={undoDone}>Annuler</button>
					</p>
				{/if}
				<button class="plain link toggle" onclick={toggleDone} aria-expanded={done !== null}>
					{done ? 'Masquer les tâches terminées' : 'Afficher les tâches terminées'}
				</button>
				{#if done}
					<ul class="done">
						{#each done as task (task.id)}
							<li>
								<input type="checkbox" checked onchange={() => setStatus(task, 'open')} aria-label="Rouvrir « {task.title} »" />
								<span>{task.title}</span>
								{#if task.done_at}<small>{dueLabel(task.done_at.slice(0, 10))}</small>{/if}
							</li>
						{:else}
							<li class="muted">Aucune tâche terminée.</li>
						{/each}
					</ul>
				{/if}
			</section>
			<section aria-labelledby="journal-title">
				<h2 id="journal-title">
					Journal <small>{entries.length} {entries.length > 1 ? 'entrées' : 'entrée'}</small>
					{#if entries.length}<a class="thread" href="/fil?projet={project.id}">Lire le fil →</a>{/if}
				</h2>
				{#each entries as entry (entry.id)}
					{@const d = shortDate(entry.entry_date)}
					<a class="entry" href={entry.source === 'writing' ? `/ecrire/${entry.id}` : `/journal/${entry.entry_date}#e-${entry.id}`}>
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
		padding: 22px 32px 48px;
		display: flex;
		flex-direction: column;
		gap: 16px;
	}
	header {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.crumbs,
	.muted,
	small {
		color: var(--muted);
		font-size: 0.875rem;
	}
	.plain {
		padding: 0;
		font: inherit;
		color: inherit;
		text-align: left;
		background: none;
		border: 0;
	}
	h1 {
		font-size: 1.875rem;
		margin: 0;
	}
	h1 .plain:hover,
	.desc:hover {
		text-decoration: underline dotted var(--muted);
		text-underline-offset: 4px;
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
	}
	.meta {
		display: flex;
		gap: 14px;
		font-size: 0.8125rem;
	}
	.meta label {
		display: flex;
		gap: 6px;
		align-items: center;
		color: var(--muted);
	}
	select,
	input,
	textarea {
		font: inherit;
		color: var(--ink);
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 6px;
	}
	select {
		padding: 2px 4px;
	}
	.desc {
		color: var(--muted);
		white-space: pre-line;
		max-width: 70ch;
	}
	.add-desc {
		font-size: 0.875rem;
		color: var(--muted);
	}
	.desc-input {
		max-width: 70ch;
		padding: 6px 8px;
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
	.message {
		margin: 0;
		padding: 8px 12px;
		color: var(--warn);
		background: var(--warn-soft);
		border-radius: 8px;
	}
	h2 {
		font-size: 1.125rem;
		padding-bottom: 4px;
		border-bottom: var(--rule);
		margin: 0;
	}
	h2 small {
		font-family: var(--sans);
		font-weight: 400;
	}
	.cols {
		display: grid;
		grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr);
		gap: 28px;
		align-items: start;
	}
	.tasks {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.tasks > li {
		border-bottom: 1px solid var(--line);
	}
	.tasks > li.dragging {
		opacity: 0.4;
	}
	.tasks > li.drop-before {
		box-shadow: inset 0 2px 0 var(--accent);
	}
	.tasks > li.drop-after {
		box-shadow: inset 0 -2px 0 var(--accent);
	}
	.tasks > li.open {
		background: var(--surface);
	}
	.row {
		display: grid;
		grid-template-columns: 28px 20px minmax(0, 1fr) auto;
		gap: 8px;
		align-items: center;
		min-height: 40px;
		padding: 2px 6px 2px 0;
	}
	.grip {
		height: 32px;
		padding: 0;
		background: none;
		border: 0;
		border-radius: 6px;
		cursor: grab;
	}
	.grip:hover,
	.grip:focus-visible {
		background: var(--soft);
	}
	.n {
		font-family: var(--serif);
		font-weight: 600;
		color: var(--accent);
	}
	.check {
		width: 16px;
		height: 16px;
		accent-color: var(--accent);
	}
	.title {
		font-weight: 700;
		padding: 6px 0;
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
		font-weight: 700;
	}
	.waiting {
		color: var(--warn);
		font-weight: 700;
	}
	.late {
		color: var(--warn);
		font-weight: 700;
	}
	.steps {
		font-variant-numeric: tabular-nums;
	}
	.detail {
		display: flex;
		flex-direction: column;
		gap: 12px;
		padding: 6px 12px 14px 56px;
	}
	.t-title {
		font-weight: 700;
		padding: 6px 8px;
	}
	.status {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.seg {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		min-height: 32px;
		padding: 0 10px;
		font-size: 0.875rem;
		color: var(--ink);
		background: transparent;
		border: 1px solid var(--line);
		border-radius: 16px;
	}
	.seg.on {
		font-weight: 700;
		background: var(--soft);
		border-color: var(--accent);
	}
	.seg select {
		border: 0;
		background: transparent;
	}
	.field {
		display: flex;
		flex-direction: column;
		gap: 4px;
		font-size: 0.8125rem;
		font-weight: 700;
		color: var(--muted);
	}
	.field input,
	.field textarea {
		font-weight: 400;
		font-size: 0.9375rem;
		padding: 6px 8px;
	}
	.field input[type='date'] {
		align-self: flex-start;
	}
	.steps-list {
		list-style: none;
		margin: 0;
		padding: 0;
		font-weight: 400;
		font-size: 0.9375rem;
		color: var(--ink);
	}
	.steps-list li {
		display: grid;
		grid-template-columns: 20px minmax(0, 1fr) 28px;
		gap: 8px;
		align-items: center;
		min-height: 30px;
	}
	.steps-list input {
		accent-color: var(--accent);
	}
	.struck {
		text-decoration: line-through;
		color: var(--muted);
	}
	.x {
		height: 28px;
		font-size: 1.1rem;
		color: var(--muted);
		background: none;
		border: 0;
		border-radius: 6px;
		opacity: 0;
	}
	.steps-list li:hover .x,
	.x:focus-visible {
		opacity: 1;
	}
	@media (hover: none) {
		.x {
			opacity: 1;
		}
	}
	.inline {
		display: flex;
		gap: 6px;
	}
	.inline input {
		flex: 1;
		font-weight: 400;
		padding: 6px 8px;
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}
	.actions .danger {
		margin-left: auto;
	}
	.danger {
		color: var(--warn);
	}
	.new input {
		width: 100%;
		box-sizing: border-box;
		margin-top: 8px;
		padding: 8px 10px;
		background: transparent;
		border-style: dashed;
	}
	.new input:focus {
		background: var(--surface);
		border-style: solid;
	}
	.undo {
		margin: 8px 0 0;
		font-size: 0.875rem;
	}
	.link {
		color: var(--accent);
		font-size: 0.875rem;
		text-decoration: underline;
	}
	.toggle {
		margin-top: 14px;
	}
	.done {
		list-style: none;
		margin: 6px 0 0;
		padding: 0;
	}
	.done li {
		display: flex;
		gap: 8px;
		align-items: center;
		min-height: 32px;
		color: var(--muted);
	}
	.done li span {
		text-decoration: line-through;
	}
	.done input {
		accent-color: var(--accent);
	}
	.empty {
		padding: 10px 0;
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
	@media (max-width: 600px) {
		.wrap {
			padding: 16px;
		}
		.row {
			grid-template-columns: 28px 20px minmax(0, 1fr);
		}
		.info {
			grid-column: 3;
			justify-content: flex-start;
		}
		.detail {
			padding-left: 12px;
		}
	}
	.task-people {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		align-items: center;
	}
	.task-people .chip {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 2px 4px 2px 10px;
		font-size: 0.875rem;
		background: var(--chip);
		border-radius: 999px;
	}
	.task-people .x {
		opacity: 1;
		height: 22px;
		width: 22px;
		padding: 0;
	}
	.task-people .chip a {
		text-decoration: none;
		font-weight: 700;
	}
	.thread {
		float: right;
		font-family: var(--sans);
		font-size: 0.8125rem;
		font-weight: 400;
		color: var(--accent);
	}
</style>
