<script lang="ts">
	// The memo of a space or a project: a few lines kept at hand (addresses, user names, numbers,
	// what not to forget). Markdown; each line « Libellé : valeur » can be copied in one click.
	// `folded`: shown as one line that opens (the space's memo on its projects' pages).
	import { tick } from 'svelte';
	import { ApiError } from '../api.js';
	import { v2, type Memo } from '../api2.js';
	import { toHtml } from './writing/export.js';
	import { failure } from './state.svelte.js';

	let { ownerId, label = 'Mémo', folded = false }: { ownerId: string; label?: string; folded?: boolean } = $props();

	let memo = $state<Memo | null>(null);
	let editing = $state(false);
	let draft = $state('');
	let saving = $state(false);
	let message = $state('');
	let expanded = $state(false);
	let long = $state(false);
	let versions = $state<{ body: string; saved_at: string }[] | null>(null);
	let area: HTMLTextAreaElement | undefined = $state();
	let copied = $state('');

	$effect(() => {
		const id = ownerId;
		memo = null;
		editing = false;
		versions = null;
		message = '';
		v2.memo(id).then(
			(m) => {
				if (id === ownerId) memo = m;
			},
			(err) => (message = failure(err, 'Mémo non chargé : '))
		);
	});

	let html = $derived(memo?.body ? toHtml(memo.body, true) : '');

	async function edit(body = memo?.body ?? '') {
		draft = body;
		editing = true;
		message = '';
		await tick();
		area?.focus();
		grow();
	}

	function grow() {
		if (!area) return;
		area.style.height = 'auto';
		area.style.height = `${Math.min(area.scrollHeight + 2, window.innerHeight * 0.7)}px`;
	}

	async function save() {
		if (!memo || saving) return;
		saving = true;
		message = '';
		try {
			memo = await v2.saveMemo(ownerId, draft, memo.revision);
			editing = false;
			versions = null;
		} catch (err) {
			if (err instanceof ApiError && err.status === 409) {
				message = 'Le mémo a été modifié ailleurs entre-temps. Ton texte est gardé ci-dessous ; recharge pour voir l’autre version.';
			} else {
				message = failure(err, 'Mémo non enregistré : ');
			}
		} finally {
			saving = false;
		}
	}

	async function reloadMemo() {
		try {
			memo = await v2.memo(ownerId);
			message = '';
		} catch (err) {
			message = failure(err, '');
		}
	}

	function cancel() {
		if (draft !== (memo?.body ?? '') && !confirm('Abandonner les modifications du mémo ?')) return;
		editing = false;
		message = '';
	}

	async function showVersions() {
		if (versions) {
			versions = null;
			return;
		}
		try {
			versions = await v2.memoVersions(ownerId);
		} catch (err) {
			message = failure(err, '');
		}
	}

	/** « Libellé : valeur » → the value; otherwise the whole line. */
	function valueOf(text: string): string {
		const t = text.replace(/\s+/g, ' ').trim();
		const m = /^[^:]{1,40}?\s?:\s+(.+)$/.exec(t);
		return m ? m[1].trim() : t;
	}

	async function copy(text: string) {
		try {
			await navigator.clipboard.writeText(text);
		} catch {
			const ta = document.createElement('textarea');
			ta.value = text;
			document.body.append(ta);
			ta.select();
			document.execCommand('copy');
			ta.remove();
		}
		copied = text;
		setTimeout(() => {
			if (copied === text) copied = '';
		}, 1500);
	}

	// Links open apart; each paragraph or list line gets a small « copier » button.
	function enhance(node: HTMLElement, _html: string) {
		function apply() {
			node.querySelectorAll('.copy').forEach((b) => b.remove());
			node.querySelectorAll('a[href]').forEach((a) => {
				a.setAttribute('target', '_blank');
				a.setAttribute('rel', 'noopener noreferrer');
			});
			// Lines of one paragraph (separated by <br>): one span each, so each line is copied apart.
			node.querySelectorAll('p:has(> br)').forEach((p) => {
				const lines: Node[][] = [[]];
				for (const child of [...p.childNodes]) {
					if (child.nodeName === 'BR') lines.push([]);
					else lines[lines.length - 1].push(child);
				}
				p.replaceChildren(
					...lines.map((nodes) => {
						const span = document.createElement('span');
						span.className = 'line';
						span.append(...nodes);
						return span;
					})
				);
			});
			node.querySelectorAll('p:not(:has(> .line)), li, .line').forEach((el) => {
				if (el.querySelector(':scope > p, :scope > ul, :scope > ol')) return; // its own lines get one
				const text = (el.textContent ?? '').trim();
				if (!text) return;
				const value = valueOf(text);
				const button = document.createElement('button');
				button.type = 'button';
				button.className = 'copy';
				button.textContent = 'copier';
				button.title = `Copier « ${value.length > 60 ? value.slice(0, 60) + '…' : value} »`;
				button.addEventListener('click', (e) => {
					e.stopPropagation();
					void copy(value);
					button.textContent = 'copié ✓';
					setTimeout(() => (button.textContent = 'copier'), 1500);
				});
				el.append(button);
			});
			long = node.scrollHeight > 260;
		}
		apply();
		return { update: () => void tick().then(apply) };
	}

	function when(iso: string): string {
		return new Date(iso).toLocaleString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
	}
</script>

{#if memo && (!folded || memo.body || editing)}
	<section class="memo" class:folded id={folded ? undefined : 'memo'} aria-label={label}>
		{#if folded && !editing}
			<details>
				<summary>{label}</summary>
				<div class="body" use:enhance={html}>{@html html}</div>
				<button class="link" onclick={() => edit()}>Modifier</button>
			</details>
		{:else if editing}
			<div class="head"><strong>{label}</strong></div>
			<textarea
				bind:this={area}
				bind:value={draft}
				oninput={grow}
				rows="4"
				aria-label={label}
				placeholder={'Adresse du wiki : https://…\nIdentifiant : …\nÀ ne pas oublier : …'}
				onkeydown={(e) => {
					if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
						e.preventDefault();
						void save();
					} else if (e.key === 'Escape') {
						e.preventDefault();
						cancel();
					}
				}}
			></textarea>
			<div class="actions">
				<button class="primary" disabled={saving} onclick={save}>{saving ? 'Enregistrement…' : 'Enregistrer'}</button>
				<button class="link" onclick={cancel}>Annuler</button>
				<small>Ctrl+Entrée enregistre · Markdown · une ligne « Libellé : valeur » se copie d’un clic · pas de mots de passe ici</small>
			</div>
		{:else if memo.body}
			<div class="head">
				<strong>{label}</strong>
				<button class="link" onclick={() => edit()}>Modifier</button>
				<button class="link" onclick={showVersions}>{versions ? 'Masquer les versions' : 'Versions'}</button>
			</div>
			<div class="body" class:clipped={long && !expanded} use:enhance={html}>{@html html}</div>
			{#if long}
				<button class="link more" onclick={() => (expanded = !expanded)}>{expanded ? 'Replier' : 'Tout voir'}</button>
			{/if}
		{:else}
			<button class="add" onclick={() => edit()} title="Identifiants, adresses, numéros, infos à garder sous la main">+ Mémo</button>
		{/if}
		{#if versions}
			<ul class="versions">
				{#each versions as v, i (i)}
					<li>
						<span>{when(v.saved_at)}</span>
						<span class="preview">{v.body.split('\n')[0]}</span>
						<button class="link" onclick={() => edit(v.body)}>Rétablir</button>
					</li>
				{:else}
					<li class="muted">Aucune version précédente.</li>
				{/each}
			</ul>
		{/if}
		{#if message}
			<p class="warn" role="alert">
				{message}
				{#if message.startsWith('Le mémo a été modifié')}<button class="link" onclick={reloadMemo}>Recharger</button>{/if}
			</p>
		{/if}
		{#if copied}<span class="sr" role="status">Copié</span>{/if}
	</section>
{/if}

<style>
	.memo {
		border: 1px solid var(--line);
		border-left: 3px solid var(--accent);
		border-radius: 6px;
		padding: 8px 12px;
		background: var(--softer);
		font-family: var(--sans);
		font-size: 0.9375rem;
		max-width: 760px;
	}
	.memo:has(> .add) {
		border: 0;
		padding: 0;
		background: none;
	}
	.memo.folded {
		padding: 4px 12px;
	}
	summary {
		cursor: pointer;
		color: var(--muted);
		font-size: 0.875rem;
	}
	details[open] summary {
		margin-bottom: 4px;
	}
	.head {
		display: flex;
		align-items: baseline;
		gap: 12px;
		margin-bottom: 2px;
	}
	.head strong {
		font-size: 0.8125rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--muted);
	}
	.body {
		overflow-wrap: anywhere;
	}
	.body.clipped {
		max-height: 220px;
		overflow: hidden;
		mask-image: linear-gradient(to bottom, #000 75%, transparent);
	}
	.body :global(p),
	.body :global(ul),
	.body :global(ol) {
		margin: 2px 0;
	}
	.body :global(ul),
	.body :global(ol) {
		padding-left: 20px;
	}
	.body :global(h1),
	.body :global(h2),
	.body :global(h3) {
		font-size: 0.9375rem;
		margin: 8px 0 2px;
	}
	.body :global(code) {
		font-size: 0.875em;
		background: var(--bg, #fff);
		padding: 0 3px;
		border-radius: 3px;
	}
	.body :global(.copy) {
		margin-left: 8px;
		padding: 0 6px;
		border: 1px solid var(--line);
		border-radius: 4px;
		background: var(--bg, #fff);
		font: inherit;
		font-size: 0.75rem;
		color: var(--muted);
		cursor: pointer;
		opacity: 0;
	}
	.body :global(.line) {
		display: block;
	}
	.body :global(.line:hover > .copy),
	.body :global(p:hover > .copy),
	.body :global(li:hover > .copy),
	.body :global(.copy:focus-visible) {
		opacity: 1;
	}
	@media (hover: none) {
		.body :global(.copy) {
			opacity: 0.7;
		}
	}
	textarea {
		width: 100%;
		box-sizing: border-box;
		font-family: var(--mono, monospace);
		font-size: 0.875rem;
		padding: 6px 8px;
		border: 1px solid var(--line);
		border-radius: 4px;
		resize: vertical;
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 10px;
		margin-top: 4px;
	}
	.actions small,
	.muted {
		color: var(--muted);
		font-size: 0.8125rem;
	}
	.primary {
		padding: 3px 12px;
		border: 0;
		border-radius: 4px;
		background: var(--accent);
		color: #fff;
		font: inherit;
		cursor: pointer;
	}
	.link {
		padding: 0;
		border: 0;
		background: none;
		font: inherit;
		font-size: 0.8125rem;
		color: var(--accent);
		cursor: pointer;
	}
	.more {
		margin-top: 2px;
	}
	.add {
		padding: 3px 10px;
		border: 1px dashed var(--line);
		border-radius: 6px;
		background: none;
		font: inherit;
		font-size: 0.8125rem;
		color: var(--muted);
		cursor: pointer;
	}
	.add:hover {
		color: var(--accent);
		border-color: var(--accent);
	}
	.versions {
		list-style: none;
		margin: 8px 0 0;
		padding: 6px 0 0;
		border-top: 1px solid var(--line);
		font-size: 0.8125rem;
	}
	.versions li {
		display: flex;
		gap: 10px;
		align-items: baseline;
		padding: 2px 0;
	}
	.versions li > span:first-child {
		color: var(--muted);
		white-space: nowrap;
	}
	.preview {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.warn {
		margin: 6px 0 0;
		color: var(--warn);
		font-size: 0.8125rem;
	}
	.sr {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0 0 0 0);
	}
</style>
