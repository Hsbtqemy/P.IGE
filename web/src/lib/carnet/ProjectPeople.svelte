<script lang="ts">
	// The people of a project: added from the directory, each with an optional role; those of
	// the parent project are shown too (managed on the parent's page).
	import { v2, type ProjectView } from '../api2.js';
	import PersonPicker from './PersonPicker.svelte';
	import { failure, projectOf } from './state.svelte.js';

	let { project, onchange }: { project: ProjectView; onchange: (p: ProjectView) => void } = $props();

	let message = $state('');
	let editing = $state<string | null>(null);
	let roleDraft = $state('');
	let own = $derived(project.people.filter((p) => !p.inherited));
	let inherited = $derived(project.people.filter((p) => p.inherited));

	async function run(what: string, action: () => Promise<ProjectView>) {
		message = '';
		try {
			onchange(await action());
		} catch (err) {
			message = failure(err, `${what} : `);
		}
	}

	function startRole(id: string, role: string | null) {
		editing = id;
		roleDraft = role ?? '';
	}

	function saveRole(id: string) {
		if (editing !== id) return;
		editing = null;
		void run('Rôle non enregistré', () => v2.setProjectPerson(project.id, id, roleDraft.trim() || null));
	}
</script>

<div class="people" aria-label="Personnes du projet">
	<span class="label">Personnes</span>
	<ul>
		{#each own as p (p.id)}
			<li>
				<a href="/personnes/{p.id}">{p.display_name}</a>
				{#if editing === p.id}
					<input
						class="role-input"
						bind:value={roleDraft}
						maxlength="120"
						placeholder="rôle"
						aria-label="Rôle de {p.display_name}"
						onblur={() => saveRole(p.id)}
						onkeydown={(e) => {
							if (e.key === 'Enter') (e.currentTarget as HTMLInputElement).blur();
							if (e.key === 'Escape') editing = null;
						}}
					/>
				{:else}
					<button class="role" onclick={() => startRole(p.id, p.project_role)} title="Changer le rôle">
						{p.project_role || '+ rôle'}
					</button>
				{/if}
				<button
					class="x"
					onclick={() => run('Personne non retirée', () => v2.removeProjectPerson(project.id, p.id))}
					aria-label="Retirer {p.display_name} du projet">×</button
				>
			</li>
		{/each}
		{#each inherited as p (p.id)}
			<li class="inherited" title="Personne du projet parent, à gérer sur sa page">
				<a href="/personnes/{p.id}">{p.display_name}</a>
				<small>{p.project_role ? `${p.project_role} · ` : ''}{projectOf(project.parent_id ?? '')?.name ?? 'projet parent'}</small>
			</li>
		{/each}
		<li class="add">
			<PersonPicker
				id="project-person"
				exclude={own.map((p) => p.id)}
				onpick={(person) => run('Personne non ajoutée', () => v2.setProjectPerson(project.id, person.id, null))}
			/>
		</li>
	</ul>
	{#if message}<p class="warn" role="alert">{message}</p>{/if}
</div>

<style>
	.people {
		display: flex;
		flex-wrap: wrap;
		gap: 6px 10px;
		align-items: baseline;
	}
	.label {
		font-size: 0.8125rem;
		font-weight: 700;
		color: var(--muted);
	}
	ul {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin: 0;
		padding: 0;
		list-style: none;
		align-items: center;
	}
	li {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 2px 4px 2px 10px;
		font-size: 0.875rem;
		background: var(--chip);
		border-radius: 999px;
	}
	li.inherited {
		padding-right: 10px;
		background: transparent;
		border: 1px dashed var(--line);
	}
	li.add {
		padding: 0;
		background: none;
	}
	a {
		text-decoration: none;
		font-weight: 700;
	}
	small {
		color: var(--muted);
	}
	.role {
		padding: 0;
		background: none;
		border: 0;
		font: inherit;
		font-size: 0.8125rem;
		color: var(--muted);
		cursor: pointer;
	}
	.role:hover {
		color: var(--accent);
		text-decoration: underline;
	}
	.role-input {
		width: 9em;
		font: inherit;
		font-size: 0.8125rem;
		padding: 1px 6px;
		border: 1px solid var(--line);
		border-radius: 6px;
		background: var(--surface);
		color: var(--ink);
	}
	.x {
		width: 22px;
		height: 22px;
		padding: 0;
		border: 0;
		border-radius: 50%;
		background: none;
		color: var(--muted);
		cursor: pointer;
	}
	.x:hover {
		color: var(--warn);
	}
	.warn {
		flex-basis: 100%;
		margin: 0;
		color: var(--warn);
		font-size: 0.875rem;
	}
</style>
