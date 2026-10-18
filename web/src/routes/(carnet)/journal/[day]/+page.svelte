<script lang="ts">
	import { page } from '$app/state';
	import { ApiError } from '#lib/api.js';
	import { v2, type Entry } from '#lib/api2.js';
	import { read, segments, type Reading } from '#lib/feuillet.js';
	import {
		allProjects,
		carnet,
		defaultSpace,
		longDate,
		projectOf,
		reload,
		shiftDay,
		spaceOf,
		todayIso
	} from '#lib/carnet/state.svelte.js';

	const DAY = /^\d{4}-\d{2}-\d{2}$/;

	let day = $derived(DAY.test(page.params.day ?? '') ? (page.params.day as string) : '');
	let entries = $state<Entry[]>([]);
	let writtenDays = $state<string[]>([]);
	let loading = $state(true);
	let message = $state('');

	let draft = $state('');
	let placeChoice = $state(''); // '' = automatic, 'p:<id>' project, 's:<id>' space
	let saving = $state(false);
	let composer: HTMLTextAreaElement | undefined = $state();

	let editingId = $state<string | null>(null);
	let editText = $state('');
	let editPlace = $state('');

	let known = $derived(allProjects().map((p) => ({ id: p.id, name: p.name, space_id: p.space_id })));
	let reading = $derived(read(draft, known, carnet.people));

	type Place = { project_id: string | null; space_id: string | null; label: string; auto: boolean };

	function placeFor(r: Reading, choice: string): Place | null {
		if (choice.startsWith('p:')) {
			const p = projectOf(choice.slice(2));
			if (p) return { project_id: p.id, space_id: null, label: p.name, auto: false };
		}
		if (choice.startsWith('s:')) {
			const s = spaceOf(choice.slice(2));
			if (s) return { project_id: null, space_id: s.id, label: s.name, auto: false };
		}
		if (r.project) return { project_id: r.project.id, space_id: null, label: r.project.name, auto: true };
		const s = defaultSpace();
		return s ? { project_id: null, space_id: s.id, label: s.name, auto: true } : null;
	}

	let place = $derived(placeFor(reading, placeChoice));

	function placeLabel(e: Entry): string {
		return projectOf(e.project_id)?.name ?? spaceOf(e.space_id)?.name ?? '';
	}

	function nowHHMM(): string {
		const d = new Date();
		return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
	}

	function sortDay(list: Entry[]): Entry[] {
		return [...list].sort(
			(a, b) =>
				(a.start_time ?? '99:99').localeCompare(b.start_time ?? '99:99') || a.created_at.localeCompare(b.created_at)
		);
	}

	async function load(target: string): Promise<void> {
		loading = true;
		message = '';
		try {
			const [list, days] = await Promise.all([v2.timeline({ day: target }), v2.journalDays(target.slice(0, 7))]);
			if (target !== day) return; // navigated meanwhile
			entries = sortDay(list);
			writtenDays = days;
		} catch (err) {
			message = err instanceof ApiError && err.status === 0 ? 'Hors connexion.' : 'Impossible de charger le feuillet.';
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		if (day) {
			editingId = null;
			void load(day);
		}
	});

	async function createTasks(tasks: string[], target: Place, entryId: string): Promise<void> {
		for (const title of tasks) {
			await v2.createTask({ title, project_id: target.project_id, space_id: target.space_id, origin_entry_id: entryId });
		}
	}

	async function add(): Promise<void> {
		const text = draft.trim();
		if (!text || !place || saving) return;
		saving = true;
		message = '';
		const r = read(text, known, carnet.people);
		const target = place;
		try {
			const entry = await v2.createEntry({
				entry_date: day,
				project_id: target.project_id,
				space_id: target.space_id,
				kind: r.kind,
				title: r.title,
				body: text,
				start_time: day === todayIso() ? nowHHMM() : null,
				source: 'journal',
				people: r.people,
				tags: r.tags
			});
			await createTasks(r.tasks, target, entry.id);
			draft = '';
			placeChoice = '';
			await Promise.all([load(day), reload()]);
			composer?.focus();
		} catch (err) {
			message = err instanceof ApiError ? `Non enregistré : ${err.message}` : 'Non enregistré.';
		} finally {
			saving = false;
		}
	}

	function startEdit(e: Entry): void {
		editingId = e.id;
		editText = e.body;
		editPlace = e.project_id ? `p:${e.project_id}` : `s:${e.space_id}`;
	}

	async function saveEdit(e: Entry): Promise<void> {
		const text = editText.trim();
		if (!text || saving) return;
		saving = true;
		message = '';
		const r = read(text, known, carnet.people);
		const before = new Set(read(e.body, known, carnet.people).tasks);
		const target = placeFor(r, editPlace);
		try {
			await v2.updateEntry(e.id, {
				expected_revision: e.revision,
				body: text,
				title: r.title,
				kind: r.kind,
				people: r.people,
				tags: r.tags
			});
			if (target && (target.project_id !== e.project_id || (!target.project_id && target.space_id !== e.space_id))) {
				await v2.moveEntry(e.id, { project_id: target.project_id, space_id: target.space_id });
			}
			if (target) await createTasks(r.tasks.filter((t) => !before.has(t)), target, e.id);
			editingId = null;
			await Promise.all([load(day), reload()]);
		} catch (err) {
			if (err instanceof ApiError && err.status === 409) {
				message = 'Ce paragraphe a été modifié ailleurs entre-temps : il est rechargé, recopie ta modification.';
				editingId = null;
				await load(day);
			} else {
				message = err instanceof ApiError ? `Non enregistré : ${err.message}` : 'Non enregistré.';
			}
		} finally {
			saving = false;
		}
	}

	async function remove(e: Entry): Promise<void> {
		if (!confirm('Supprimer ce paragraphe ? Les tâches créées depuis lui sont gardées.')) return;
		try {
			await v2.deleteEntry(e.id);
			editingId = null;
			await Promise.all([load(day), reload()]);
		} catch (err) {
			message = err instanceof ApiError ? `Suppression impossible : ${err.message}` : 'Suppression impossible.';
		}
	}

	function keys(event: KeyboardEvent, action: () => void, cancel?: () => void): void {
		if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
			event.preventDefault();
			action();
		} else if (event.key === 'Escape' && cancel) {
			cancel();
		}
	}

	// ------------------------------------------------ side panel

	let filedIn = $derived.by(() => {
		const counts = new Map<string, { kind: string; name: string; href: string | null; n: number }>();
		for (const e of entries) {
			const p = projectOf(e.project_id);
			const key = p ? `p:${p.id}` : `s:${e.space_id}`;
			const item = counts.get(key) ?? {
				kind: p ? 'Projet' : 'Espace',
				name: p?.name ?? spaceOf(e.space_id)?.name ?? '?',
				href: p ? `/projets/${p.id}` : null,
				n: 0
			};
			item.n += 1;
			counts.set(key, item);
		}
		return [...counts.values()];
	});

	let peopleOfDay = $derived.by(() => {
		const seen = new Map<string, string>();
		for (const e of entries) for (const p of e.people) seen.set(p.id, p.display_name);
		return [...seen.values()];
	});

	let calendar = $derived.by(() => {
		if (!day) return [];
		const [y, m] = day.split('-').map(Number);
		const first = new Date(y, m - 1, 1);
		const blanks = (first.getDay() + 6) % 7; // Monday first
		const count = new Date(y, m, 0).getDate();
		const cells: ({ iso: string; n: number } | null)[] = Array(blanks).fill(null);
		for (let d = 1; d <= count; d++) cells.push({ iso: `${day.slice(0, 7)}-${String(d).padStart(2, '0')}`, n: d });
		return cells;
	});
	let monthName = $derived(
		day ? new Date(`${day}T12:00:00`).toLocaleDateString('fr-FR', { month: 'long', year: 'numeric' }) : ''
	);
</script>

<svelte:head><title>{day ? longDate(day) : 'Journal'} · P.IGE</title></svelte:head>

{#if !day}
	<p class="pad">Date invalide. <a href="/journal/{todayIso()}">Aller à aujourd’hui</a></p>
{:else}
	<div class="journal">
		<section class="page-col">
			<header>
				<nav class="days" aria-label="Autres jours">
					<a href="/journal/{shiftDay(day, -1)}" aria-label="Jour précédent">‹ {longDate(shiftDay(day, -1))}</a>
					{#if day !== todayIso()}<a href="/journal/{todayIso()}">Aujourd’hui</a>{/if}
					<a href="/journal/{shiftDay(day, 1)}" aria-label="Jour suivant">{longDate(shiftDay(day, 1))} ›</a>
				</nav>
				<h1>{longDate(day)}</h1>
			</header>

			{#if message}<p class="message" role="status">{message}</p>{/if}

			<article class="sheet" aria-busy={loading}>
				{#each entries as entry (entry.id)}
					<div class="para">
						<div class="margin">
							<span class="time">{entry.start_time ?? ''}</span>
							<span class="where">{placeLabel(entry)}</span>
							{#if editingId !== entry.id}
								<button class="edit" onclick={() => startEdit(entry)}>Modifier</button>
							{/if}
						</div>
						{#if editingId === entry.id}
							<div class="body editing">
								<label class="visually-hidden" for="edit-{entry.id}">Modifier le paragraphe</label>
								<textarea
									id="edit-{entry.id}"
									bind:value={editText}
									rows={Math.max(3, editText.split('\n').length + 1)}
									onkeydown={(ev) => keys(ev, () => saveEdit(entry), () => (editingId = null))}
								></textarea>
								<div class="row">
									<select bind:value={editPlace} aria-label="Ranger dans">
										{#each carnet.tree?.spaces ?? [] as space (space.id)}
											<optgroup label={space.name}>
												<option value="s:{space.id}">{space.name} (espace)</option>
												{#each space.projects as p (p.id)}
													<option value="p:{p.id}">{p.parent_id ? '— ' : ''}{p.name}</option>
												{/each}
											</optgroup>
										{/each}
									</select>
									<button class="btn" onclick={() => remove(entry)}>Supprimer</button>
									<span class="grow"></span>
									<button class="btn" onclick={() => (editingId = null)}>Annuler</button>
									<button class="btn primary" disabled={saving} onclick={() => saveEdit(entry)}>Enregistrer</button>
								</div>
							</div>
						{:else}
							<div class="body">
								{#if entry.kind === 'meeting'}<span class="kind">Réunion</span>{/if}
								{#each entry.body.split('\n') as line, i (i)}
									{#if line.trim()}
										<p>
											{#each segments(line) as seg, j (j)}
												{#if seg.type === 'person'}<span class="chip-person">{seg.text}</span
													>{:else if seg.type === 'tag'}<span class="chip-tag">{seg.text}</span
													>{:else if seg.type === 'decision'}<span class="kind decision">DÉCISION</span
													>{:else if seg.type === 'task'}<span class="task"
														><span class="box" aria-hidden="true"></span>{seg.text}<small>tâche</small></span
													>{:else}{seg.text}{/if}
											{/each}
										</p>
									{/if}
								{/each}
								<span class="where-inline">{placeLabel(entry)}</span>
							</div>
						{/if}
					</div>
				{:else}
					{#if !loading}<p class="empty">Rien d’écrit ce jour-là.</p>{/if}
				{/each}

				<div class="para compose">
					<div class="margin">
						<span class="time">{day === todayIso() ? nowHHMM() : ''}</span>
					</div>
					<div class="body">
						<label class="visually-hidden" for="composer">Écrire un paragraphe</label>
						<textarea
							id="composer"
							bind:this={composer}
							bind:value={draft}
							rows={Math.max(3, draft.split('\n').length + 1)}
							placeholder="Écrire… Un nom de projet le range, @personne, #étiquette, [ ] tâche, Décision :"
							onkeydown={(ev) => keys(ev, add)}
						></textarea>
						{#if draft.trim()}
							<div class="preview" aria-live="polite">
								<span class="label">Sera rangé dans</span>
								<select bind:value={placeChoice} aria-label="Ranger dans">
									<option value="">{place?.auto ? `${place.label} (reconnu)` : 'Automatique'}</option>
									{#each carnet.tree?.spaces ?? [] as space (space.id)}
										<optgroup label={space.name}>
											<option value="s:{space.id}">{space.name} (espace)</option>
											{#each space.projects as p (p.id)}
												<option value="p:{p.id}">{p.parent_id ? '— ' : ''}{p.name}</option>
											{/each}
										</optgroup>
									{/each}
								</select>
								{#each reading.people as person (person)}<span class="chip-person">@{person}</span>{/each}
								{#each reading.tags as tag (tag)}<span class="chip-tag">#{tag}</span>{/each}
								{#if reading.tasks.length}<span class="count">{reading.tasks.length} tâche{reading.tasks.length > 1 ? 's' : ''}</span>{/if}
								{#if reading.kind === 'decision'}<span class="kind decision">DÉCISION</span>{/if}
							</div>
						{/if}
						<div class="row">
							<span class="hint">Ctrl + Entrée pour ajouter</span>
							<span class="grow"></span>
							<button class="btn primary" disabled={!draft.trim() || saving || !place} onclick={add}>Ajouter au feuillet</button>
						</div>
					</div>
				</div>
			</article>
		</section>

		<aside class="side" aria-label="Ce que le feuillet a relié">
			<div class="block">
				<span class="label">Rangé dans</span>
				{#each filedIn as item (item.kind + item.name)}
					<div class="line">
						{#if item.href}<a href={item.href}>{item.name}</a>{:else}<span>{item.name}</span>{/if}
						<small>{item.kind} · {item.n} §</small>
					</div>
				{:else}
					<p class="muted">Rien encore.</p>
				{/each}
			</div>
			{#if peopleOfDay.length}
				<div class="block">
					<span class="label">Personnes citées</span>
					<p>{peopleOfDay.join(' · ')}</p>
				</div>
			{/if}
			<div class="help">
				<b>Écrire sans formulaire</b>
				<span>Un nom de projet range le paragraphe, <b>@</b> cite une personne, <b>#</b> pose une étiquette, une ligne <b>[ ]</b> crée une tâche, <b>Décision :</b> en fait une décision.</span>
			</div>
			<div class="block">
				<span class="label">{monthName}</span>
				<div class="cal">
					{#each ['L', 'M', 'M', 'J', 'V', 'S', 'D'] as d, i (i)}<span class="head">{d}</span>{/each}
					{#each calendar as cell, i (i)}
						{#if cell}
							<a
								href="/journal/{cell.iso}"
								class:written={writtenDays.includes(cell.iso)}
								class:current={cell.iso === day}
								aria-current={cell.iso === day ? 'date' : undefined}>{cell.n}</a
							>
						{:else}<span></span>{/if}
					{/each}
				</div>
				<small class="muted">Jours teintés : un feuillet écrit.</small>
			</div>
		</aside>
	</div>
{/if}

<style>
	.pad {
		padding: 24px 32px;
	}
	.journal {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 290px;
		min-height: 100dvh;
	}
	.page-col {
		padding: 22px 32px 32px;
		display: flex;
		flex-direction: column;
		gap: 14px;
		min-width: 0;
	}
	.days {
		display: flex;
		gap: 14px;
		font-size: 0.875rem;
		color: var(--muted);
	}
	.days a {
		color: var(--muted);
	}
	h1 {
		font-size: 1.875rem;
	}
	.message {
		margin: 0;
		padding: 8px 12px;
		background: var(--warn-soft);
		border-left: 4px solid var(--warn);
		border-radius: 6px;
	}
	.sheet {
		padding: 26px 34px 20px 18px;
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 10px;
		font-family: var(--serif);
		font-size: 1.125rem;
		line-height: 1.6;
	}
	.para {
		display: grid;
		grid-template-columns: 96px minmax(0, 1fr);
		column-gap: 18px;
	}
	.margin {
		text-align: right;
		padding-right: 14px;
		border-right: var(--margin);
		display: flex;
		flex-direction: column;
		font-family: var(--sans);
	}
	.time {
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		min-height: 1.6em;
	}
	.where {
		font-size: 0.75rem;
		line-height: 1.3;
		color: var(--muted);
		overflow-wrap: break-word;
		hyphens: auto;
	}
	.body {
		position: relative;
		padding-bottom: 16px;
		min-width: 0;
	}
	.where-inline {
		display: none;
		font-family: var(--sans);
		font-size: 0.75rem;
		color: var(--muted);
	}
	.body p {
		margin: 0 0 4px;
		overflow-wrap: anywhere;
	}
	.kind {
		display: inline-block;
		margin-right: 6px;
		font-family: var(--sans);
		font-size: 0.75rem;
		font-weight: 700;
		color: var(--accent);
	}
	.kind.decision {
		color: var(--decision);
	}
	.task {
		display: inline-flex;
		gap: 8px;
		align-items: baseline;
	}
	.task .box {
		flex: none;
		width: 14px;
		height: 14px;
		border: 2px solid var(--muted);
		border-radius: 3px;
		transform: translateY(2px);
	}
	.task small {
		white-space: nowrap;
		font-family: var(--sans);
		font-size: 0.75rem;
		color: var(--accent);
	}
	.edit {
		align-self: flex-end;
		margin-top: 4px;
		padding: 2px 6px;
		font-family: var(--sans);
		font-size: 0.75rem;
		color: var(--muted);
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 6px;
		opacity: 0;
	}
	.para:hover .edit,
	.edit:focus-visible {
		opacity: 1;
	}
	textarea {
		width: 100%;
		box-sizing: border-box;
		padding: 8px 10px;
		font: inherit;
		color: var(--ink);
		background: var(--softer);
		border: 1px solid var(--line);
		border-radius: 8px;
		resize: vertical;
	}
	.compose textarea {
		background: transparent;
		border-style: dashed;
	}
	.row {
		display: flex;
		gap: 8px;
		align-items: center;
		margin-top: 8px;
		font-family: var(--sans);
	}
	.grow {
		flex: 1;
	}
	.hint {
		font-size: 0.8125rem;
		color: var(--muted);
	}
	select {
		max-width: 260px;
		min-height: 32px;
		font: inherit;
		font-family: var(--sans);
		font-size: 0.875rem;
		color: var(--ink);
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 6px;
	}
	.preview {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		align-items: center;
		margin-top: 8px;
		font-family: var(--sans);
		font-size: 0.875rem;
	}
	.count {
		color: var(--accent);
		font-weight: 700;
	}
	.empty {
		margin: 0 0 16px 114px;
		color: var(--muted);
		font-family: var(--sans);
		font-size: 0.9375rem;
	}
	.side {
		padding: 22px 20px;
		background: var(--surface);
		border-left: 1px solid var(--line);
		display: flex;
		flex-direction: column;
		gap: 18px;
		font-size: 0.875rem;
	}
	.block {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.block p {
		margin: 0;
	}
	.line {
		display: flex;
		justify-content: space-between;
		gap: 8px;
		padding: 4px 0;
		border-bottom: 1px solid var(--line);
	}
	.line small,
	.muted {
		color: var(--muted);
		margin: 0;
	}
	.help {
		padding: 10px 12px;
		background: var(--softer);
		border-radius: 8px;
		display: flex;
		flex-direction: column;
		gap: 4px;
		font-size: 0.8125rem;
	}
	.cal {
		display: grid;
		grid-template-columns: repeat(7, 1fr);
		gap: 3px;
		text-align: center;
		font-size: 0.75rem;
		font-variant-numeric: tabular-nums;
	}
	.cal .head {
		font-weight: 700;
		color: var(--muted);
	}
	.cal a {
		padding: 4px 0;
		border-radius: 4px;
		text-decoration: none;
	}
	.cal a.written {
		background: var(--soft);
	}
	.cal a.current {
		font-weight: 700;
		color: var(--accent-ink);
		background: var(--accent);
	}
	@media (max-width: 1100px) {
		.journal {
			grid-template-columns: 1fr;
		}
		.side {
			border-left: 0;
			border-top: 1px solid var(--line);
		}
	}
	@media (max-width: 600px) {
		.page-col {
			padding: 16px;
		}
		.sheet {
			padding: 16px 12px;
		}
		.para {
			grid-template-columns: 58px minmax(0, 1fr);
			column-gap: 10px;
		}
		.edit {
			opacity: 1;
			padding: 1px 4px;
			font-size: 0.6875rem;
		}
		.where {
			display: none;
		}
		.where-inline {
			display: block;
		}
		.empty {
			margin-left: 68px;
		}
	}
</style>
