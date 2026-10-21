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
	let showAll = $state(false);
	let unfolded = $state(new Set<string>());
	const FIRST = 3;
	let shown = $derived(showAll ? (code?.chantiers ?? []) : (code?.chantiers ?? []).slice(0, FIRST));

	/** pilote writes Markdown: `code` and **bold** rendered, the rest plain (escaped). */
	function inline(text: string): string {
		const esc = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
		return esc.replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>').replace(/\*\*/g, '');
	}

	const toggle = (c: string) =>
		(unfolded = unfolded.has(c) ? new Set([...unfolded].filter((x) => x !== c)) : new Set([...unfolded, c]));

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
					Chaque jour où tu pousses du code, une entrée le résume par chantier dans le journal du projet. Le plus simple :
					« npm run pige » dans le dépôt (pilote envoyer) envoie le journal de pilote, public ou privé, sans réglage
					GitHub. Sinon, l’export pilote publié (Pages) ou l’API GitHub.
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
					{#if code.pushed}
						{code.branch ? `${code.branch} · ` : ''}{code.last_sync ? `reçu ${when(code.last_sync).replace(/^lu /, '')}` : 'rien reçu'} · envoyé
						depuis le dépôt (npm run pige)
					{:else}
						{code.branch ? `${code.branch} · ` : ''}{when(code.last_sync)} · lu à 12 h 30 et 19 h 30{#if code.export_url}
							· via <a href={code.export_url.replace(/journal\.json$/, '')} target="_blank" rel="noopener">l’export pilote</a>{/if}
					{/if}
				</small>
				<span class="grow"></span>
				{#if !code.pushed}
					<button class="link" disabled={busy} onclick={() => run(() => v2.syncProjectCode(projectId))}>{busy ? 'Lecture…' : 'Actualiser'}</button>
				{/if}
				<button class="link" onclick={() => ((editing = true), (draft = code?.repo ?? ''), (exportDraft = code?.pushed ? '' : (code?.export_url ?? '').replace(/journal\.json$/, '')))}>Modifier</button>
			</header>
			{#if code.last_error}<p class="warn">{code.last_error}</p>{/if}
			{#if code.chantiers?.length}
				<ul>
					{#each shown as c (c.code)}
						<li>
							<span class="line">
								<a class="title" href={file(c.path)} target="_blank" rel="noopener"><b>{c.code}</b> {c.title}</a>
								<small><span class="status">{c.status}</span>{c.open ? ` · ${c.open} à faire` : ''}{c.last ? ` · ${new Date(`${c.last}T12:00:00`).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' })}` : ''}</small>
							</span>
							{#if c.stopped}
								<button class="stopped" class:open={unfolded.has(c.code)} onclick={() => toggle(c.code)} aria-expanded={unfolded.has(c.code)}>
									<span class="lbl">{c.stopped_label.toLocaleLowerCase('fr')} :</span>
									<!-- eslint-disable-next-line svelte/no-at-html-tags -- escaped above, only code and bold added -->
									{@html inline(c.stopped)}
								</button>
							{/if}
						</li>
					{/each}
				</ul>
				<small class="muted">
					{#if code.chantiers.length > FIRST}
						<button class="link" onclick={() => (showAll = !showAll)} aria-expanded={showAll}>
							{showAll ? 'Seulement les plus récents' : `Voir les ${code.chantiers.length} chantiers ouverts`}
						</button>
					{/if}
					{#if code.closed}{code.chantiers.length > FIRST ? ' · ' : ''}{code.closed} clos, livré{code.closed > 1 ? 's' : ''} ou abandonné{code.closed > 1 ? 's' : ''}{/if}
				</small>
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
		gap: 1px;
		padding: 5px 0;
		border-bottom: 1px solid var(--line);
	}
	.line {
		display: flex;
		flex-wrap: wrap;
		gap: 2px 10px;
		align-items: baseline;
	}
	.stopped {
		display: -webkit-box;
		-webkit-box-orient: vertical;
		-webkit-line-clamp: 1;
		line-clamp: 1;
		overflow: hidden;
		padding: 0;
		background: none;
		border: 0;
		font: inherit;
		font-size: 0.8125rem;
		color: var(--muted);
		text-align: left;
		cursor: pointer;
		overflow-wrap: anywhere;
	}
	.stopped.open {
		-webkit-line-clamp: unset;
		line-clamp: unset;
		display: block;
	}
	.stopped .lbl {
		font-style: italic;
	}
	.stopped :global(code) {
		font-size: 0.75rem;
		padding: 0 3px;
		border-radius: 3px;
		background: var(--chip);
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
