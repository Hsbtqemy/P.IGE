<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { ApiError } from '#lib/api.js';
	import { v2, type Entry, type PersonPatch, type PersonView } from '#lib/api2.js';
	import EntryList from '#lib/carnet/EntryList.svelte';
	import TaskList from '#lib/carnet/TaskList.svelte';
	import { carnet, failure, spaceOf } from '#lib/carnet/state.svelte.js';

	let id = $derived(page.params.id ?? '');
	let person = $state<PersonView | null>(null);
	let entries = $state<Entry[]>([]);
	let loadError = $state('');
	let message = $state('');
	let saved = $state('');
	let draft = $state({ display_name: '', email: '', organisation: '', role: '', note: '' });
	let newTag = $state('');

	type Field = keyof typeof draft;

	$effect(() => {
		const current = id;
		person = null;
		loadError = '';
		message = '';
		Promise.all([v2.personView(current), v2.timeline({ person_id: current, limit: 100 })])
			.then(([p, e]) => {
				if (current !== id) return;
				show(p);
				entries = e;
			})
			.catch((err) => {
				if (current !== id) return;
				loadError = err instanceof ApiError && err.status === 404 ? 'Personne introuvable.' : failure(err, 'Fiche non chargée : ');
			});
	});

	/** Show the fiche; after a save only the saved fields are refreshed, so a field being typed in is kept. */
	function show(p: PersonView, only?: string[]) {
		person = p;
		const fresh = {
			display_name: p.display_name,
			email: p.email ?? '',
			organisation: p.organisation ?? '',
			role: p.role ?? '',
			note: p.note ?? ''
		};
		if (!only) draft = fresh;
		else for (const key of only) if (key in fresh) draft[key as Field] = fresh[key as Field];
		carnet.people = carnet.people.map((x) => (x.id === p.id ? { ...x, ...p, last_exchange: x.last_exchange } : x));
	}

	async function save(patch: PersonPatch, what = 'Fiche non enregistrée') {
		if (!person) return;
		message = '';
		saved = '';
		try {
			show(await v2.updatePerson(person.id, patch), Object.keys(patch));
			saved = 'Enregistré';
			setTimeout(() => (saved = ''), 1500);
		} catch (err) {
			message = failure(err, `${what} : `);
		}
	}

	function saveField(field: Field) {
		if (!person) return;
		const value = draft[field].trim();
		const current = (person[field] ?? '') as string;
		if (value === current) return;
		if (field === 'display_name') {
			if (!value) {
				draft.display_name = person.display_name;
				return;
			}
			void save({ display_name: value });
		} else {
			void save({ [field]: value || null });
		}
	}

	function addTag(event: SubmitEvent) {
		event.preventDefault();
		const name = newTag.trim().replace(/^#/, '');
		if (!name || !person) return;
		newTag = '';
		if (person.tags.some((t) => t.name.toLowerCase() === name.toLowerCase())) return;
		void save({ tags: [...person.tags.map((t) => t.name), name] }, 'Étiquette non ajoutée');
	}

	function removeTag(tagId: string) {
		if (!person) return;
		void save({ tags: person.tags.filter((t) => t.id !== tagId).map((t) => t.name) }, 'Étiquette non retirée');
	}

	async function remove() {
		if (!person) return;
		const p = person;
		if (p.waiting_on.length) {
			message = `Des tâches attendent encore ${p.display_name} : change leur statut avant de supprimer la fiche.`;
			return;
		}
		const links = p.involved_in.length + entries.length;
		const detail = links ? ` Ses ${links} liens (tâches, journal) seront retirés, sans supprimer les tâches ni les paragraphes.` : '';
		if (!confirm(`Supprimer la fiche de ${p.display_name} ?${detail}`)) return;
		try {
			await v2.deletePerson(p.id);
			carnet.people = carnet.people.filter((x) => x.id !== p.id);
			await goto('/personnes');
		} catch (err) {
			message = failure(err, 'Fiche non supprimée : ');
		}
	}

	const FIELDS: { key: Exclude<Field, 'display_name' | 'note'>; label: string; type: string }[] = [
		{ key: 'role', label: 'Rôle', type: 'text' },
		{ key: 'organisation', label: 'Laboratoire, service', type: 'text' },
		{ key: 'email', label: 'Courriel', type: 'email' }
	];
</script>

<svelte:head><title>{person?.display_name ?? 'Personne'} · P.IGE</title></svelte:head>

<div class="wrap">
	{#if loadError}
		<p>{loadError} <a href="/personnes">Toutes les personnes</a></p>
	{:else if person}
		<header>
			<a class="crumbs" href="/personnes">‹ Personnes</a>
			<input
				class="name"
				bind:value={draft.display_name}
				onblur={() => saveField('display_name')}
				onkeydown={(e) => e.key === 'Enter' && (e.currentTarget as HTMLInputElement).blur()}
				aria-label="Nom"
			/>
			{#if person.last_exchange}
				<p class="muted">Dernier échange le {new Date(`${person.last_exchange}T12:00:00`).toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' })}</p>
			{/if}
		</header>

		{#if message}<p class="message" role="alert">{message}</p>{/if}

		<div class="cols">
			<div class="fiche">
				{#each FIELDS as f (f.key)}
					<label class="field">
						<span>{f.label}</span>
						<span class="with-action">
							<input type={f.type} bind:value={draft[f.key]} onblur={() => saveField(f.key)}
								onkeydown={(e) => e.key === 'Enter' && (e.currentTarget as HTMLInputElement).blur()} />
							{#if f.key === 'email' && person.email}<a class="mail" href="mailto:{person.email}" aria-label="Écrire à {person.display_name}">✉</a>{/if}
						</span>
					</label>
				{/each}
				<div class="field">
					<span>Étiquettes</span>
					<div class="tags">
						{#each person.tags as tag (tag.id)}
							<span class="tag">
								<a href="/etiquettes/{tag.id}">#{tag.name}</a>
								<button onclick={() => removeTag(tag.id)} aria-label="Retirer l’étiquette {tag.name}">×</button>
							</span>
						{/each}
						<form onsubmit={addTag}>
							<input bind:value={newTag} placeholder="+ étiquette" aria-label="Ajouter une étiquette" />
						</form>
					</div>
				</div>
				<label class="field">
					<span>Notes</span>
					<textarea bind:value={draft.note} rows="5" onblur={() => saveField('note')}></textarea>
				</label>
				<div class="foot">
					<span class="saved" role="status">{saved}</span>
					<button class="btn danger" onclick={remove}>Supprimer la fiche</button>
				</div>
			</div>

			<div class="links">
				<section>
					<h2>Projets <small>{person.projects.length || ''}</small></h2>
					{#each person.projects as p (p.id)}
						<a class="project" href="/projets/{p.id}">
							<b>{p.name}</b>
							<small>{[p.project_role, spaceOf(p.space_id)?.name, p.state === 'dormant' ? 'en sommeil' : p.state === 'closed' ? 'clos' : ''].filter(Boolean).join(' · ')}</small>
						</a>
					{:else}
						<p class="muted">Dans aucun projet. Ajoute-la ou ajoute-le depuis la page d’un projet.</p>
					{/each}
				</section>
				<section>
					<h2>J’attends d’elle ou de lui <small>{person.waiting_on.length || ''}</small></h2>
					<TaskList tasks={person.waiting_on} empty="Rien en attente." />
				</section>
				<section>
					<h2>Impliqué·e dans <small>{person.involved_in.length || ''}</small></h2>
					<TaskList tasks={person.involved_in} empty="Aucune tâche ouverte." />
				</section>
				<section>
					<h2>Journal <small>{entries.length || ''}</small>{#if entries.length}<a class="thread" href="/fil?personne={person.id}">Lire le fil →</a>{/if}</h2>
					<EntryList {entries} showPlace empty="Aucun paragraphe ne la ou le mentionne." />
				</section>
			</div>
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
		gap: 4px;
	}
	.crumbs {
		font-size: 0.875rem;
		color: var(--muted);
	}
	.name {
		font-family: var(--serif);
		font-size: 1.875rem;
		font-weight: 600;
		color: var(--ink);
		background: transparent;
		border: 1px solid transparent;
		border-radius: 6px;
		padding: 0 4px;
		margin-left: -5px;
	}
	.name:hover,
	.name:focus {
		border-color: var(--line);
		background: var(--surface);
	}
	small,
	.muted {
		font-family: var(--sans);
		font-weight: 400;
		font-size: 0.875rem;
		color: var(--muted);
	}
	header .muted {
		margin: 0;
	}
	.message {
		margin: 0;
		padding: 8px 12px;
		color: var(--warn);
		background: var(--warn-soft);
		border-radius: 8px;
	}
	.cols {
		display: grid;
		grid-template-columns: minmax(260px, 1fr) minmax(0, 1.4fr);
		gap: 32px;
		align-items: start;
	}
	.fiche {
		display: flex;
		flex-direction: column;
		gap: 12px;
	}
	.field {
		display: flex;
		flex-direction: column;
		gap: 4px;
		font-size: 0.8125rem;
		font-weight: 700;
		color: var(--muted);
	}
	input,
	textarea {
		font: inherit;
		font-weight: 400;
		font-size: 0.9375rem;
		color: var(--ink);
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 6px;
		padding: 6px 8px;
		min-width: 0;
	}
	.with-action {
		display: flex;
		gap: 6px;
		align-items: center;
	}
	.with-action input {
		flex: 1;
	}
	.mail {
		font-size: 1.1rem;
		text-decoration: none;
		color: var(--accent);
	}
	.tags {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		align-items: center;
		font-weight: 400;
	}
	.tag {
		display: inline-flex;
		align-items: center;
		gap: 2px;
		padding: 2px 4px 2px 9px;
		font-size: 0.875rem;
		color: var(--ink);
		background: var(--chip);
		border-radius: 12px;
	}
	.tag a {
		text-decoration: none;
	}
	.tag button {
		width: 22px;
		height: 22px;
		padding: 0;
		color: var(--muted);
		background: none;
		border: 0;
		border-radius: 50%;
	}
	.tags input {
		width: 120px;
		padding: 3px 8px;
		font-size: 0.875rem;
		border-style: dashed;
	}
	.foot {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}
	.saved {
		font-size: 0.8125rem;
		color: var(--muted);
	}
	.danger {
		color: var(--warn);
	}
	.links {
		display: flex;
		flex-direction: column;
		gap: 22px;
	}
	h2 {
		font-size: 1.125rem;
		padding-bottom: 4px;
		border-bottom: var(--rule);
		margin: 0;
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
		.name {
			width: 100%;
			font-size: 1.5rem;
		}
	}
	.project {
		display: flex;
		flex-direction: column;
		padding: 8px 0;
		border-bottom: 1px solid var(--line);
		text-decoration: none;
	}
	.project small {
		color: var(--muted);
		font-size: 0.875rem;
	}
	.thread {
		float: right;
		font-family: var(--sans);
		font-size: 0.8125rem;
		font-weight: 400;
		color: var(--accent);
	}
</style>
