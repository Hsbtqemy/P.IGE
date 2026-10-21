<script lang="ts">
	// A project's repository: link it, and see its open work items (pilote's pilotage/),
	// read as they are on GitHub — never copied into tasks.
	import { v2, type ProjectCode } from '../api2.js';
	import { failure } from './state.svelte.js';

	let { projectId }: { projectId: string } = $props();

	let code = $state<ProjectCode | null>(null);
	let editing = $state(false);
	let draft = $state('');
	let exportDraft = $state('');
	let busy = $state(false);
	let message = $state('');

	$effect(() => {
		const current = projectId;
		code = null;
		editing = false;
		v2.projectCode(current)
			.then((c) => {
				if (current === projectId) code = c;
			})
			.catch(() => {});
	});

	async function run(action: () => Promise<ProjectCode>) {
		busy = true;
		message = '';
		try {
			code = await action();
			editing = false;
		} catch (err) {
			message = failure(err, '');
		} finally {
			busy = false;
		}
	}

	function save(event: SubmitEvent) {
		event.preventDefault();
		void run(() => v2.setProjectRepo(projectId, draft.trim() || null, exportDraft.trim() || null));
	}

	function when(iso: string | null | undefined): string {
		if (!iso) return 'jamais lu';
		return 'lu ' + new Date(iso).toLocaleString('fr-FR', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
	}

	const file = (path: string) => `https://github.com/${code?.repo}/blob/${code?.branch ?? 'HEAD'}/${path}`;
</script>

{#if code}
	<section class="code" aria-label="Code">
		{#if editing || !code.repo}
			{#if editing}
				<form onsubmit={save}>
					<input bind:value={draft} placeholder="propriétaire/dépôt ou adresse GitHub" aria-label="Dépôt GitHub" />
					<input
						bind:value={exportDraft}
						placeholder="Export pilote sur GitHub Pages (facultatif) : https://…github.io/depot/"
						aria-label="Adresse de l’export pilote"
						inputmode="url"
					/>
					<button class="btn primary" disabled={busy}>{busy ? 'Lecture…' : 'Relier'}</button>
					<button type="button" class="btn" onclick={() => (editing = false)}>Annuler</button>
					{#if code.repo}<button type="button" class="btn" onclick={() => run(() => v2.setProjectRepo(projectId, null))}>Délier</button>{/if}
				</form>
				<small class="muted">
					Chaque jour où tu pousses du code, une entrée le résume par chantier dans le journal du projet. Avec l’export
					pilote (dépôt public), P.IGE lit ce seul fichier : ni limite ni jeton.
					{#if !code.token}Sans export, un dépôt privé demande un jeton GitHub sur le serveur (voir deploy/README).{/if}
				</small>
			{:else}
				<button class="link" onclick={() => ((editing = true), (draft = ''), (exportDraft = ''))}>+ Relier un dépôt de code</button>
			{/if}
		{:else}
			<header>
				<span class="label">Code</span>
				<a href="https://github.com/{code.repo}" target="_blank" rel="noopener">{code.repo}</a>
				<small class="muted">
					{code.branch ? `${code.branch} · ` : ''}{when(code.last_sync)} · lu à 12 h 30 et 19 h 30{#if code.export_url}
						· via <a href={code.export_url.replace(/journal\.json$/, '')} target="_blank" rel="noopener">l’export pilote</a>{/if}
				</small>
				<span class="grow"></span>
				<button class="link" disabled={busy} onclick={() => run(() => v2.syncProjectCode(projectId))}>{busy ? 'Lecture…' : 'Actualiser'}</button>
				<button class="link" onclick={() => ((editing = true), (draft = code?.repo ?? ''), (exportDraft = (code?.export_url ?? '').replace(/journal\.json$/, '')))}>Modifier</button>
			</header>
			{#if code.last_error}<p class="warn">{code.last_error}</p>{/if}
			{#if code.chantiers?.length}
				<ul>
					{#each code.chantiers as c (c.code)}
						<li>
							<a class="title" href={file(c.path)} target="_blank" rel="noopener"><b>{c.code}</b> {c.title}</a>
							<small>
								<span class="status">{c.status}</span>{c.open ? ` · ${c.open} à faire` : ''}
								{#if c.stopped} · {c.stopped_label.toLocaleLowerCase('fr')} : {c.stopped}{/if}
							</small>
						</li>
					{/each}
				</ul>
				{#if code.closed}<small class="muted">et {code.closed} chantier{code.closed > 1 ? 's' : ''} clos, livré{code.closed > 1 ? 's' : ''} ou abandonné{code.closed > 1 ? 's' : ''}</small>{/if}
			{:else if !code.last_error}
				<small class="muted">Pas de chantier ouvert dans pilotage/.</small>
			{/if}
		{/if}
		{#if message}<p class="warn" role="alert">{message}</p>{/if}
	</section>
{/if}

<style>
	.code {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	header {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 10px;
		align-items: baseline;
	}
	.label {
		font-size: 0.8125rem;
		font-weight: 700;
		color: var(--muted);
	}
	.grow {
		flex: 1;
	}
	form {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	input {
		flex: 1 1 220px;
		min-width: 0;
		font: inherit;
		font-size: 0.9375rem;
		padding: 5px 8px;
		color: var(--ink);
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 6px;
	}
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	li {
		display: flex;
		flex-direction: column;
		padding: 5px 0;
		border-bottom: 1px solid var(--line);
	}
	.title {
		text-decoration: none;
		overflow-wrap: anywhere;
	}
	.title b {
		font-family: ui-monospace, Menlo, Consolas, monospace;
		font-size: 0.875rem;
		color: var(--accent);
	}
	.status {
		font-weight: 700;
	}
	small,
	.muted {
		color: var(--muted);
		font-size: 0.8125rem;
		overflow-wrap: anywhere;
	}
	.warn {
		margin: 0;
		color: var(--warn);
		font-size: 0.875rem;
	}
	.link {
		padding: 0;
		background: none;
		border: 0;
		font: inherit;
		font-size: 0.8125rem;
		color: var(--accent);
		text-decoration: underline;
		cursor: pointer;
		align-self: flex-start;
	}
</style>
