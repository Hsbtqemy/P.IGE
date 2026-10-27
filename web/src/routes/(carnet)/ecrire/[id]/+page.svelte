<script lang="ts">
	import { onDestroy } from 'svelte';
	import { beforeNavigate, goto } from '$app/navigation';
	import { page } from '$app/state';
	import { ApiError } from '#lib/api.js';
	import { v2, type Entry, type EntryPatch, type EntryVersion, type Task } from '#lib/api2.js';
	import Editor from '#lib/carnet/writing/Editor.svelte';
	import {
		copyFormatted,
		downloadMarkdown,
		downloadWord,
		mailLink,
		printPdf,
		toHtml
	} from '#lib/carnet/writing/export.js';
	import { outline } from '#lib/carnet/writing/livePreview.js';
	import { boxes, sameTitle } from '#lib/carnet/writing/boxes.js';
	import { carnet, failure, isDay, placeName, reload, timeZone } from '#lib/carnet/state.svelte.js';
	import { showRange } from '#lib/carnet/timerange.js';

	let id = $derived(page.params.id ?? '');
	let entry = $state<Entry | null>(null);
	let loadError = $state('');
	let text = $state('');
	let titleDraft = $state('');
	let editor = $state<Editor | null>(null);

	let saving = $state(false);
	let pending = false;
	let failed = $state('');
	let lastSaved = $state<Date | null>(null);
	let other = $state<Entry | null>(null); // the text saved elsewhere, on conflict
	let timer: ReturnType<typeof setTimeout> | undefined;

	let panel = $state<'plan' | 'versions' | 'export'>('plan');
	let versions = $state<EntryVersion[] | null>(null);
	let preview = $state<EntryVersion | null>(null);
	let notice = $state('');

	// The text's checkboxes and the tasks made from them (a ticked task ticks its box, both ways).
	let textTasks = $state<Task[]>([]);
	let creating = $state(false);
	let allBoxes = $derived(boxes(text));
	let missing = $derived(allBoxes.filter((b) => !b.done && !textTasks.some((t) => sameTitle(t.title, b.title))));
	let followed = $derived(allBoxes.filter((b) => textTasks.some((t) => sameTitle(t.title, b.title))).length);

	let dirty = $derived(!!entry && (text !== entry.body || titleDraft.trim() !== entry.title));
	let plan = $derived(outline(text));
	let wordCount = $derived(text.split(/\s+/).filter((w) => /[\p{L}\p{N}]/u.test(w)).length);

	$effect(() => {
		const current = id;
		entry = null;
		loadError = '';
		other = null;
		versions = null;
		preview = null;
		v2.entry(current)
			.then((e) => {
				if (current !== id) return;
				entry = e;
				text = e.body;
				titleDraft = e.title;
				void loadTasks(current);
			})
			.catch((err) => {
				if (current !== id) return;
				loadError = err instanceof ApiError && err.status === 404 ? 'Texte introuvable.' : failure(err, 'Texte non chargé : ');
			});
	});

	function schedule(ms = 1200) {
		clearTimeout(timer);
		timer = setTimeout(() => void flush(), ms);
	}

	function onchange(value: string) {
		text = value;
		if (!other) schedule();
	}

	/** Save what changed. ``explicit`` (Ctrl S, restore) always keeps the previous text as a version. */
	async function flush(explicit = false) {
		clearTimeout(timer);
		if (!entry || other || deleting) return;
		if (saving) {
			pending = true;
			return;
		}
		const patch: EntryPatch = { expected_revision: entry.revision, autosave: !explicit };
		if (text !== entry.body) patch.body = text;
		const title = titleDraft.trim();
		if (title && title !== entry.title) patch.title = title;
		if (patch.body === undefined && patch.title === undefined) return;
		saving = true;
		failed = '';
		try {
			const saved = await v2.updateEntry(entry.id, patch);
			entry = saved;
			lastSaved = new Date();
			if (versions && explicit) versions = await v2.entryVersions(saved.id);
		} catch (err) {
			if (err instanceof ApiError && err.status === 409) {
				try {
					other = await v2.entry(entry.id);
				} catch {
					failed = 'Modifié ailleurs, et la version de l’autre appareil n’a pas pu être lue.';
				}
			} else {
				failed = failure(err, 'Non enregistré : ');
			}
		} finally {
			saving = false;
		}
		if (pending || (!other && !failed && dirty)) {
			pending = false;
			schedule(300);
		}
	}

	// What these notes are about: something of the agenda of the text's day.
	let choices = $state<{ key: string; label: string }[]>([]);
	let linking = $state(false);
	$effect(() => {
		const day = entry?.entry_date;
		const current = id;
		if (!day) return;
		const clock = (iso: string) => new Date(iso).toLocaleTimeString('fr-FR', { hour: 'numeric', minute: '2-digit' });
		Promise.all([v2.agenda(day, 1, timeZone()).catch(() => []), v2.planned(day, 1, timeZone()).catch(() => [])]).then(([events, planned]) => {
			if (current !== id) return;
			choices = [
				...events
					.filter((e) => e.status !== 'removed')
					.map((e) => ({ key: `v:${e.id}`, label: `${e.all_day ? 'Journée' : clock(e.start)} · ${e.title}` })),
				...planned
					.filter((p) => p.id !== current && p.source !== 'writing')
					.map((p) => ({ key: `e:${p.id}`, label: `${p.start_time ? showRange(p.start_time, null) : 'Journée'} · ${p.title || p.body.slice(0, 60)}` }))
			];
		});
	});

	async function linkTo(key: string) {
		if (!entry || !key) return;
		linking = true;
		await settle();
		try {
			entry = await v2.setAbout(entry.id, key.startsWith('v:') ? { event_id: key.slice(2) } : { entry_id: key.slice(2) });
		} catch (err) {
			failed = failure(err, 'Lien non fait : ');
		} finally {
			linking = false;
		}
	}

	async function unlink() {
		if (!entry) return;
		linking = true;
		await settle();
		try {
			entry = await v2.setAbout(entry.id, {});
		} catch (err) {
			failed = failure(err, 'Lien non défait : ');
		} finally {
			linking = false;
		}
	}

	async function loadTasks(current = id) {
		try {
			const list = await v2.entryTasks(current);
			if (current === id) textTasks = list;
		} catch {
			/* the boxes still work; only the link with tasks is missing */
		}
	}

	/** Everything typed is saved (so the server, ticking a box for a task, finds the same text). */
	async function settle() {
		for (let i = 0; i < 20 && (saving || dirty) && !other; i++) {
			if (saving) await new Promise((r) => setTimeout(r, 150));
			else await flush();
		}
	}

	async function createTasks() {
		if (!entry || !missing.length) return;
		const where = placeName(entry);
		if (!confirm(`Créer ${missing.length} tâche${missing.length > 1 ? 's' : ''} dans « ${where} » ? Cocher une tâche cochera sa case ici, et l’inverse.`)) return;
		creating = true;
		await settle();
		const target = entry.project_id ? { project_id: entry.project_id } : { space_id: entry.space_id };
		let failedCount = 0;
		for (const b of missing) {
			try {
				await v2.createTask({ title: b.title, ...target, origin_entry_id: entry.id });
			} catch {
				failedCount += 1;
			}
		}
		await loadTasks();
		reload().catch(() => {});
		creating = false;
		notice = failedCount ? `${failedCount} tâche${failedCount > 1 ? 's' : ''} non créée${failedCount > 1 ? 's' : ''}.` : `Tâches créées dans « ${where} ».`;
	}

	/** A box ticked in the text: its task follows. */
	async function ontoggle(title: string, done: boolean) {
		const task = textTasks.find((t) => sameTitle(t.title, title));
		if (!task || (task.status === 'done') === done) return;
		await settle();
		try {
			await v2.updateTask(task.id, { status: done ? 'done' : 'open' });
			await loadTasks();
			reload().catch(() => {});
		} catch (err) {
			failed = failure(err, 'Tâche non mise à jour : ');
		}
	}

	async function keepMine() {
		if (!other) return;
		entry = other;
		other = null;
		await flush(true);
	}

	function takeTheirs() {
		if (!other) return;
		const theirs = other;
		other = null;
		entry = theirs;
		titleDraft = theirs.title;
		text = theirs.body;
		editor?.setText(theirs.body);
	}

	async function setDate(value: string) {
		if (!entry || !isDay(value) || value === entry.entry_date) return;
		await flush(true);
		try {
			entry = await v2.updateEntry(entry.id, { expected_revision: entry.revision, entry_date: value });
		} catch (err) {
			failed = failure(err, 'Date non modifiée : ');
		}
	}

	async function setPlace(value: string) {
		if (!entry) return;
		const to = value.startsWith('p:') ? { project_id: value.slice(2) } : { space_id: value.slice(2) };
		try {
			entry = await v2.moveEntry(entry.id, to);
		} catch (err) {
			failed = failure(err, 'Texte non déplacé : ');
		}
	}

	async function openVersions() {
		panel = 'versions';
		preview = null;
		if (!entry) return;
		try {
			versions = await v2.entryVersions(entry.id);
		} catch (err) {
			failed = failure(err, 'Versions non chargées : ');
		}
	}

	async function restore(v: EntryVersion) {
		if (!confirm(`Revenir à la version du ${stamp(v.saved_at)} ? Le texte actuel sera gardé comme version.`)) return;
		editor?.setText(v.body);
		text = v.body;
		preview = null;
		await flush(true);
		notice = 'Version restaurée. Le texte d’avant est dans les versions.';
	}

	function stamp(iso: string): string {
		return new Date(iso).toLocaleString('fr-FR', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
	}

	function title(): string {
		return titleDraft.trim() || entry?.title || 'Texte';
	}

	async function copy() {
		try {
			await copyFormatted(text);
			notice = 'Copié, avec la mise en forme : colle-le dans un mail.';
		} catch {
			notice = 'Copie refusée par le navigateur.';
		}
	}

	function pdf() {
		if (!printPdf(title(), text)) notice = 'Le navigateur a bloqué la fenêtre d’impression : autorise les fenêtres pour ce site.';
	}

	let mail = $derived(mailLink(titleDraft.trim() || 'Texte', text));

	let deleting = $state(false); // once deleted, nothing is saved any more

	async function remove() {
		if (!entry) return;
		const tasks = textTasks.length ? ` Les ${textTasks.length} tâche${textTasks.length > 1 ? 's' : ''} créée${textTasks.length > 1 ? 's' : ''} depuis ses cases sont gardées.` : '';
		if (!confirm(`Supprimer « ${title()} » et ses versions ? C’est définitif.${tasks}`)) return;
		deleting = true;
		clearTimeout(timer);
		try {
			await v2.deleteEntry(entry.id);
			reload().catch(() => {});
			await goto('/ecrire');
		} catch (err) {
			deleting = false;
			failed = failure(err, 'Texte non supprimé : ');
		}
	}

	function onBeforeUnload(event: BeforeUnloadEvent) {
		if (!deleting && (dirty || saving)) event.preventDefault();
	}

	beforeNavigate(() => {
		if (dirty && !deleting) void flush();
	});
	onDestroy(() => clearTimeout(timer));
</script>

<svelte:window onbeforeunload={onBeforeUnload} />
<svelte:head><title>{titleDraft || 'Écrire'} · P.IGE</title></svelte:head>

<div class="wrap">
	{#if loadError}
		<p>{loadError} <a href="/ecrire">Tous les textes</a></p>
	{:else if entry}
		<header>
			<div class="bar">
				<a class="crumbs" href="/ecrire">‹ Textes</a>
				<span class="status" role="status">
					{#if other}Conflit{:else if failed}Non enregistré{:else if saving}Enregistrement…{:else if dirty}Modifié{:else if lastSaved}Enregistré à {lastSaved.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}{:else}À jour{/if}
					· {wordCount} mots
				</span>
			</div>
			<input
				class="title"
				bind:value={titleDraft}
				oninput={() => schedule()}
				onkeydown={(e) => e.key === 'Enter' && (e.preventDefault(), editor?.focus())}
				aria-label="Titre"
				placeholder="Titre"
			/>
			<div class="meta">
				<select value={entry.project_id ? `p:${entry.project_id}` : `s:${entry.space_id}`} onchange={(e) => setPlace((e.currentTarget as HTMLSelectElement).value)} aria-label="Projet ou espace">
					{#each carnet.tree?.spaces ?? [] as space (space.id)}
						<optgroup label={space.name}>
							<option value="s:{space.id}">{space.name} (sans projet)</option>
							{#each space.projects as project (project.id)}<option value="p:{project.id}">{project.name}</option>{/each}
						</optgroup>
					{/each}
					{#if !carnet.tree?.spaces.some((s) => s.id === entry?.space_id)}<option value="s:{entry.space_id}">{placeName(entry)}</option>{/if}
				</select>
				<input type="date" value={entry.entry_date} onchange={(e) => setDate((e.currentTarget as HTMLInputElement).value)} aria-label="Date" />
				{#if entry.about}
					{@const a = entry.about}
					<span class="about">
						Notes de :
						<a href={a.kind === 'event' ? `/agenda/${a.day}` : `/journal/${a.day}#e-${a.entry_id}`}><b>{a.title}</b></a>
						{#if a.start_time}· {showRange(a.start_time, a.end_time)}{/if}{#if a.location}{' · '}{a.location}{/if}
						<button class="unlink" disabled={linking} onclick={unlink} aria-label="Défaire le lien avec « {a.title} »" title="Défaire le lien">×</button>
					</span>
				{:else if choices.length}
					<select value="" disabled={linking} onchange={(e) => linkTo((e.currentTarget as HTMLSelectElement).value)} aria-label="Notes de…">
						<option value="">Notes de… (agenda du jour)</option>
						{#each choices as c (c.key)}<option value={c.key}>{c.label}</option>{/each}
					</select>
				{/if}
			</div>
		</header>

		{#if other}
			<div class="conflict" role="alert">
				<p><b>Ce texte a été modifié sur un autre appareil.</b> Ta version est toujours dans l’éditeur.</p>
				<div class="row">
					<button class="btn primary" onclick={keepMine}>Garder ma version</button>
					<button class="btn" onclick={takeTheirs}>Prendre l’autre version</button>
				</div>
			</div>
		{/if}
		{#if failed}<p class="message" role="alert">{failed} <button class="btn" onclick={() => flush(true)}>Réessayer</button></p>{/if}
		{#if notice}<p class="notice" role="status">{notice} <button class="link" onclick={() => (notice = '')}>OK</button></p>{/if}

		<div class="cols">
			<div class="page">
				{#key entry.id}
					<Editor bind:this={editor} value={entry.body} {onchange} onsave={() => flush(true)} {ontoggle} />
				{/key}
			</div>
			<aside>
				{#if allBoxes.length}
					<div class="boxes">
						<p>
							<b>{allBoxes.filter((b) => b.done).length}/{allBoxes.length}</b> cases cochées{#if followed}{' · '}{followed} suivie{followed > 1 ? 's' : ''} en tâche{followed > 1 ? 's' : ''}{/if}
						</p>
						{#if missing.length}
							<button class="btn" disabled={creating} onclick={createTasks}>
								{creating ? 'Création…' : `Créer ${missing.length === 1 ? 'la tâche' : `les ${missing.length} tâches`}`}
							</button>
						{/if}
					</div>
				{/if}
				<div class="tabs" role="tablist" aria-label="Outils">
					<button role="tab" aria-selected={panel === 'plan'} onclick={() => (panel = 'plan')}>Plan</button>
					<button role="tab" aria-selected={panel === 'versions'} onclick={openVersions}>Versions</button>
					<button role="tab" aria-selected={panel === 'export'} onclick={() => (panel = 'export')}>Exporter</button>
				</div>
				{#if panel === 'plan'}
					<nav class="plan" aria-label="Plan du texte">
						{#each plan as h (h.line)}
							<button class="lvl{h.level}" onclick={() => editor?.jump(h.line)}>{h.text}</button>
						{:else}
							<p class="muted">Les titres (#, ##, ###) forment le plan.</p>
						{/each}
					</nav>
				{:else if panel === 'versions'}
					<div class="versions">
						<p class="muted">Une version est gardée après une pause, toutes les quinze minutes d’écriture, et à chaque Ctrl S.</p>
						{#if !versions}
							<p class="muted">Chargement…</p>
						{:else}
							{#each versions as v (v.version)}
								<button class="version" class:on={preview?.version === v.version} onclick={() => (preview = preview?.version === v.version ? null : v)}>
									<b>{stamp(v.saved_at)}</b>
									<small>{v.body.split(/\s+/).filter(Boolean).length} mots</small>
								</button>
							{:else}
								<p class="muted">Pas encore d’ancienne version.</p>
							{/each}
						{/if}
					</div>
				{:else}
					<div class="exports">
						<button class="btn" onclick={() => downloadMarkdown(title(), text)}>Markdown (.md)</button>
						<button class="btn" onclick={() => downloadWord(title(), text)}>Word (.doc)</button>
						<button class="btn" onclick={pdf}>PDF (impression)</button>
						<button class="btn" onclick={copy}>Copier mis en forme</button>
						<a class="btn" href={mail.href}>Préparer un mail</a>
						<p class="muted">
							Le mail s’ouvre dans ta messagerie (Thunderbird) : rien n’est envoyé sans toi.
							{#if mail.tooLong}Texte long : certaines messageries le coupent, préfère « Copier mis en forme ».{/if}
						</p>
					</div>
				{/if}
				<button class="delete" disabled={deleting} onclick={remove}>Supprimer ce texte</button>
			</aside>
		</div>

		{#if preview}
			<div class="preview" role="dialog" aria-label="Version du {stamp(preview.saved_at)}">
				<div class="preview-bar">
					<b>Version du {stamp(preview.saved_at)}</b>
					<span class="grow"></span>
					<button class="btn primary" onclick={() => preview && restore(preview)}>Revenir à cette version</button>
					<button class="btn" onclick={() => (preview = null)}>Fermer</button>
				</div>
				<!-- eslint-disable-next-line svelte/no-at-html-tags -- sanitised by DOMPurify in toHtml -->
				<div class="rendered">{@html toHtml(preview.body)}</div>
			</div>
		{/if}
	{:else}
		<p>Chargement…</p>
	{/if}
</div>

<style>
	.delete {
		margin-top: 24px;
		padding: 0;
		border: 0;
		background: none;
		font: inherit;
		font-family: var(--sans);
		font-size: 0.8125rem;
		color: var(--muted);
		text-decoration: underline;
		cursor: pointer;
	}
	.delete:hover {
		color: var(--warn);
	}
	.boxes {
		display: flex;
		flex-wrap: wrap;
		gap: 6px 10px;
		align-items: center;
		padding: 8px 10px;
		margin-bottom: 10px;
		background: var(--soft);
		border-radius: 8px;
		font-size: 0.875rem;
	}
	.boxes p {
		margin: 0;
	}
	.wrap {
		padding: 18px 32px 0;
		display: flex;
		flex-direction: column;
		gap: 10px;
	}
	header {
		display: flex;
		flex-direction: column;
		gap: 6px;
		max-width: 72ch;
	}
	.bar {
		display: flex;
		justify-content: space-between;
		gap: 12px;
		font-size: 0.875rem;
	}
	.crumbs,
	.status,
	.muted,
	small {
		color: var(--muted);
		font-size: 0.875rem;
	}
	.title {
		font-family: var(--serif);
		font-size: 2rem;
		font-weight: 600;
		color: var(--ink);
		background: transparent;
		border: 0;
		padding: 0;
		outline: none;
	}
	.meta {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		align-items: center;
	}
	.about {
		font-size: 0.875rem;
		color: var(--muted);
	}
	.about a {
		color: var(--ink);
	}
	.unlink {
		border: 0;
		background: none;
		color: var(--muted);
		cursor: pointer;
	}
	.unlink:hover {
		color: var(--warn);
	}
	select,
	input[type='date'] {
		font: inherit;
		font-size: 0.875rem;
		color: var(--muted);
		background: transparent;
		border: 1px solid var(--line);
		border-radius: 6px;
		padding: 3px 6px;
		max-width: 100%;
	}
	.conflict,
	.message,
	.notice {
		max-width: 72ch;
		margin: 0;
		padding: 10px 12px;
		border-radius: 8px;
	}
	.conflict,
	.message {
		color: var(--warn);
		background: var(--warn-soft);
	}
	.conflict p {
		margin: 0 0 8px;
	}
	.notice {
		background: var(--soft);
	}
	.row {
		display: flex;
		gap: 8px;
	}
	.link {
		font: inherit;
		color: var(--accent);
		text-decoration: underline;
		background: none;
		border: 0;
	}
	.cols {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 250px;
		gap: 32px;
		align-items: start;
	}
	.page {
		min-width: 0;
		border-top: 1px solid var(--line);
		padding-top: 6px;
	}
	aside {
		position: sticky;
		top: 16px;
		display: flex;
		flex-direction: column;
		gap: 10px;
		max-height: calc(100dvh - 32px);
		overflow-y: auto;
	}
	.tabs {
		display: flex;
		gap: 2px;
		border-bottom: 1px solid var(--line);
	}
	.tabs button {
		flex: 1;
		padding: 6px 4px;
		font: inherit;
		font-size: 0.8125rem;
		color: var(--muted);
		background: none;
		border: 0;
		border-bottom: 2px solid transparent;
		cursor: pointer;
	}
	.tabs button[aria-selected='true'] {
		color: var(--ink);
		font-weight: 700;
		border-bottom-color: var(--accent);
	}
	.plan {
		display: flex;
		flex-direction: column;
	}
	.plan button {
		padding: 4px 6px;
		font: inherit;
		font-size: 0.875rem;
		text-align: left;
		color: var(--ink);
		background: none;
		border: 0;
		border-radius: 6px;
		cursor: pointer;
	}
	.plan button:hover {
		background: var(--soft);
	}
	.plan .lvl1 {
		font-weight: 700;
	}
	.plan .lvl2 {
		padding-left: 16px;
	}
	.plan .lvl3 {
		padding-left: 28px;
		color: var(--muted);
	}
	.versions,
	.exports {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.versions .muted,
	.exports .muted {
		margin: 0 0 4px;
		font-size: 0.8125rem;
	}
	.version {
		display: flex;
		justify-content: space-between;
		gap: 8px;
		padding: 6px 8px;
		font: inherit;
		font-size: 0.875rem;
		color: var(--ink);
		background: none;
		border: 1px solid var(--line);
		border-radius: 6px;
		cursor: pointer;
	}
	.version.on {
		background: var(--soft);
		border-color: var(--accent);
	}
	.exports .btn {
		display: flex;
		align-items: center;
		text-decoration: none;
	}
	.preview {
		position: fixed;
		inset: 5vh 8vw;
		z-index: 15;
		display: flex;
		flex-direction: column;
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 12px;
		box-shadow: 0 18px 48px rgb(0 0 0 / 0.22);
	}
	.preview-bar {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		align-items: center;
		padding: 10px 14px;
		border-bottom: 1px solid var(--line);
	}
	.grow {
		flex: 1;
	}
	.rendered {
		overflow-y: auto;
		padding: 8px 28px 28px;
		max-width: 72ch;
		line-height: 1.6;
	}
	.rendered :global(h1),
	.rendered :global(h2),
	.rendered :global(h3) {
		font-family: var(--serif);
	}
	@media (max-width: 900px) {
		.cols {
			grid-template-columns: 1fr;
		}
		aside {
			position: static;
			max-height: none;
			order: -1;
		}
		.plan {
			max-height: 30vh;
			overflow-y: auto;
		}
	}
	@media (max-width: 600px) {
		.wrap {
			padding: 14px 16px 0;
		}
		.title {
			font-size: 1.5rem;
		}
		.preview {
			inset: 8px;
		}
	}
</style>
