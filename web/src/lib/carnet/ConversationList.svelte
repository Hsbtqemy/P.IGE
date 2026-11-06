<script lang="ts">
	// The mails of a project (or of a space without project), by conversation: everything of an
	// exchange together, wherever it was kept (filed in the journal, or in a task's follow-up).
	// A click unfolds the thread, readable without Thunderbird.
	import { tick } from 'svelte';
	import { page } from '$app/state';
	import { v2, type Conversation, type ConversationMail, type ConversationState, type KeptAttachment } from '../api2.js';
	import MailOpen from './MailOpen.svelte';
	import Attachments from './Attachments.svelte';
	import { failure } from './state.svelte.js';

	let { projectId, spaceId }: { projectId?: string; spaceId?: string } = $props();

	let list = $state<Conversation[] | null>(null);
	let query = $state('');
	let message = $state('');
	let openId = $state<string | null>(null);
	let mails = $state<ConversationMail[]>([]);
	let unfolded = $state(new Set<string>());
	let showAll = $state(false);
	const FIRST = 8;
	// « Pièces jointes »: every file kept from these mails, in one list.
	let view = $state<'conversations' | 'files'>('conversations');
	let files = $state<KeptAttachment[]>([]);

	const STATES: Record<ConversationState, string> = {
		none: '',
		to_answer: 'à répondre',
		waiting: 'attend une réponse',
		answered: 'répondu',
		filed: 'classé'
	};

	let timer: ReturnType<typeof setTimeout> | undefined;
	async function load(text = query) {
		const params = projectId ? { project_id: projectId } : { space_id: spaceId, without_project: true };
		try {
			const found = await v2.conversations({ ...params, q: text.trim() || undefined });
			if (text === query) list = found;
		} catch (err) {
			message = failure(err, 'Mails non chargés : ');
		}
	}

	$effect(() => {
		void projectId;
		void spaceId;
		list = null;
		openId = null;
		files = [];
		view = 'conversations';
		void load('');
		const params = projectId ? { project_id: projectId } : { space_id: spaceId, without_project: true };
		v2.attachments(params)
			.then((found) => (files = found))
			.catch(() => (files = []));
	});

	function showConversation(id: string) {
		view = 'conversations';
		const c = list?.find((x) => x.id === id);
		if (!c) return;
		showAll = true;
		if (openId !== id) void toggle(c);
		void tick().then(() => document.getElementById(`conv-${id}`)?.scrollIntoView({ block: 'center' }));
	}
	const fileSize = (n: number) => (n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} Ko` : `${(n / 1024 / 1024).toLocaleString('fr-FR', { maximumFractionDigits: 1 })} Mo`);

	function search() {
		clearTimeout(timer);
		timer = setTimeout(() => void load(), 250);
	}

	async function toggle(c: Conversation) {
		if (openId === c.id) {
			openId = null;
			return;
		}
		openId = c.id;
		mails = [];
		unfolded = new Set();
		try {
			const full = await v2.conversation(c.id);
			if (openId === c.id) {
				mails = full.mails;
				// The last mail open: where the exchange stands.
				if (full.mails.length) unfolded = new Set([full.mails[full.mails.length - 1].id]);
			}
		} catch (err) {
			message = failure(err, 'Conversation non chargée : ');
		}
	}

	// ?conv=<id> (from the search): that conversation, unfolded.
	let wanted = $derived(page.url.searchParams.get('conv'));
	let shownWanted = '';
	$effect(() => {
		const id = wanted;
		const all = list;
		if (!id || !all || id === shownWanted) return;
		const c = all.find((x) => x.id === id);
		if (!c) return;
		shownWanted = id;
		showAll = true;
		void toggle(c).then(() => tick()).then(() => document.getElementById(`conv-${id}`)?.scrollIntoView({ block: 'center' }));
	});

	async function setState(c: Conversation, state: ConversationState) {
		const next = c.state === state ? 'none' : state; // a second click takes it off
		try {
			const updated = await v2.setConversationState(c.id, next);
			list = (list ?? []).map((x) => (x.id === c.id ? { ...x, state: updated.state, state_since: updated.state_since } : x));
		} catch (err) {
			message = failure(err, 'État non modifié : ');
		}
	}
	const CHOICES: [ConversationState, string][] = [
		['to_answer', 'À répondre'],
		['waiting', 'J’attends sa réponse'],
		['answered', 'Répondu'],
		['filed', 'Classé']
	];

	const date = (iso: string) => new Date(iso.length > 10 ? iso : `${iso}T12:00:00`).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' });
	const firstLine = (text: string) => text.split('\n').find((l) => l.trim())?.trim() ?? '';
	let shown = $derived(list ? (showAll || query.trim() ? list : list.slice(0, FIRST)) : []);
</script>

<section class="mails" aria-labelledby="mails-title">
	<h2 id="mails-title">
		Mails <small>{list ? `${list.length} conversation${list.length > 1 ? 's' : ''}` : ''}</small>
		{#if files.length}
			<span class="tabs" role="group" aria-label="Affichage">
				<button class:on={view === 'conversations'} aria-pressed={view === 'conversations'} onclick={() => (view = 'conversations')}>Conversations</button>
				<button class:on={view === 'files'} aria-pressed={view === 'files'} onclick={() => (view = 'files')}>Pièces jointes <small>{files.length}</small></button>
			</span>
		{/if}
	</h2>
	{#if view === 'files'}
		<ul class="kept">
			{#each files as f (f.id)}
				<li>
					<a class="name" href={f.url} download={f.name} title="Télécharger">📎 {f.name}</a>
					<small>{fileSize(f.size)} · {date(f.day)}{#if f.author}{' · '}{f.author.replace(/\s*<[^>]*>/, '')}{/if}</small>
					<button class="from" onclick={() => showConversation(f.conversation_id)} title="Voir le mail">{f.subject || '(sans objet)'}</button>
				</li>
			{/each}
		</ul>
	{:else}
	{#if list && (list.length > 3 || query)}
		<input class="search" bind:value={query} oninput={search} placeholder="Chercher dans les mails (objet, personne, texte)" aria-label="Chercher dans les mails" />
	{/if}
	{#if message}<p class="warn" role="alert">{message}</p>{/if}
	{#if !list}
		<p class="muted">Chargement…</p>
	{:else}
		<ul class="convs">
			{#each shown as c (c.id)}
				<li id="conv-{c.id}" class:open={openId === c.id}>
					<button class="head" onclick={() => toggle(c)} aria-expanded={openId === c.id}>
						<span class="date">{date(c.last_at)}</span>
						<span class="what">
							<b>{c.subject || '(sans objet)'}</b>
							<small>
								{c.people.join(', ') || '—'} · {c.count} mail{c.count > 1 ? 's' : ''}{#if c.last?.direction === 'sent'}{' · '}dernier : envoyé{/if}
							</small>
						</span>
						{#if STATES[c.state]}<span class="state {c.state}">{STATES[c.state]}</span>{/if}
					</button>
					{#if c.task?.status === 'done'}
						<span class="task" title="La tâche liée à cette conversation, terminée">✓ {c.task.title}</span>
					{:else if c.task}
						<a class="task" href="?tache={c.task.id}" title="La tâche liée à cette conversation">☐ {c.task.title}</a>
					{/if}
					{#if openId === c.id}
						<div class="states" role="group" aria-label="État de la conversation">
							{#each CHOICES as [value, label] (value)}
								<button class:on={c.state === value} aria-pressed={c.state === value} onclick={() => setState(c, value)}>{label}</button>
							{/each}
						</div>
						<ol class="thread">
							{#each mails as m (m.id)}
								<li class:sent={m.direction === 'sent'}>
									<button class="mail" onclick={() => (unfolded = unfolded.has(m.id) ? new Set([...unfolded].filter((x) => x !== m.id)) : new Set([...unfolded, m.id]))} aria-expanded={unfolded.has(m.id)}>
										<span class="dir" title={m.direction === 'sent' ? 'Envoyé' : 'Reçu'}>{m.direction === 'sent' ? '↗' : '↙'}</span>
										<span class="when">{date(m.at)}</span>
										<span class="who">{m.direction === 'sent' ? `à ${m.recipients || '—'}` : `de ${m.author.replace(/\s*<[^>]*>/, '') || '—'}`}</span>
										{#if !unfolded.has(m.id)}<span class="first">{firstLine(m.body)}</span>{/if}
									</button>
									{#if unfolded.has(m.id)}
										<div class="full">
											{#if m.body.trim()}{m.body}{:else}<em>(texte non copié)</em>{/if}
											{#if m.files?.length}<Attachments files={m.files} />{:else if m.attachments}<small>Pièces jointes : {m.attachments}</small>{/if}
											<span class="links">
												{#if m.message_id}<MailOpen messageId={m.message_id} class="link" label="Ouvrir le mail" />{/if}
												{#if m.kind === 'entry'}<a class="link" href="/journal/{m.day}#e-{m.entry_id}">dans le journal</a>{:else if m.task_id}<a class="link" href="?tache={m.task_id}">dans le suivi de la tâche</a>{/if}
											</span>
										</div>
									{/if}
								</li>
							{:else}
								<li class="muted">Chargement…</li>
							{/each}
						</ol>
					{/if}
				</li>
			{:else}
				<li class="muted">{query ? 'Aucun mail ne correspond.' : 'Aucun mail rangé ici. Depuis Thunderbird : clic droit › P.IGE.'}</li>
			{/each}
		</ul>
		{#if list.length > FIRST && !showAll && !query.trim()}
			<button class="more" onclick={() => (showAll = true)}>Voir les {list.length} conversations</button>
		{/if}
	{/if}
	{/if}
</section>

<style>
	.mails {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	h2 small,
	small,
	.muted {
		font-family: var(--sans);
		font-weight: 400;
		color: var(--muted);
		font-size: 0.8125rem;
	}
	.tabs {
		display: inline-flex;
		margin-left: 10px;
		border: 1px solid var(--line);
		border-radius: 6px;
		overflow: hidden;
		vertical-align: middle;
	}
	.tabs button {
		padding: 2px 10px;
		border: 0;
		background: none;
		font: inherit;
		font-family: var(--sans);
		font-size: 0.75rem;
		font-weight: 400;
		color: var(--muted);
		cursor: pointer;
	}
	.tabs button.on {
		background: var(--soft);
		color: var(--ink);
		font-weight: 700;
	}
	.kept {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.kept li {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		gap: 2px 12px;
		padding: 7px 0;
		border-bottom: 1px solid var(--line);
		font-family: var(--sans);
		font-size: 0.875rem;
	}
	.kept .name {
		color: var(--accent);
		overflow-wrap: anywhere;
	}
	.kept .from {
		grid-column: 1 / -1;
		justify-self: start;
		padding: 0;
		border: 0;
		background: none;
		font: inherit;
		font-size: 0.8125rem;
		color: var(--muted);
		text-align: left;
		cursor: pointer;
	}
	.kept .from::before {
		content: 'dans « ';
	}
	.kept .from::after {
		content: ' »';
	}
	.kept .from:hover {
		text-decoration: underline;
	}
	.search {
		font: inherit;
		font-size: 0.875rem;
		padding: 5px 8px;
		color: var(--ink);
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 6px;
	}
	.convs,
	.thread {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.convs > li {
		border-bottom: 1px solid var(--line);
		padding: 2px 0;
	}
	.head {
		display: grid;
		grid-template-columns: 56px minmax(0, 1fr) auto;
		gap: 10px;
		align-items: baseline;
		width: 100%;
		padding: 6px 0;
		border: 0;
		background: none;
		font: inherit;
		color: var(--ink);
		text-align: left;
		cursor: pointer;
	}
	.head:hover b {
		text-decoration: underline;
	}
	.date,
	.when {
		font-family: var(--sans);
		font-size: 0.8125rem;
		color: var(--muted);
		white-space: nowrap;
	}
	.what {
		display: flex;
		flex-direction: column;
		gap: 1px;
		min-width: 0;
		overflow-wrap: anywhere;
	}
	.state {
		font-family: var(--sans);
		font-size: 0.6875rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--muted);
		white-space: nowrap;
	}
	.state.to_answer {
		color: var(--warn);
	}
	.state.waiting {
		color: var(--accent);
	}
	.task {
		display: inline-block;
		margin: 0 0 6px 66px;
		font-family: var(--sans);
		font-size: 0.8125rem;
		color: var(--muted);
	}
	.states {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
		margin: 0 0 6px 66px;
	}
	.states button {
		padding: 1px 8px;
		border: 1px solid var(--line);
		border-radius: 12px;
		background: none;
		font: inherit;
		font-family: var(--sans);
		font-size: 0.75rem;
		color: var(--muted);
		cursor: pointer;
	}
	.states button.on {
		background: var(--soft);
		color: var(--ink);
		font-weight: 700;
	}
	.thread {
		margin: 0 0 8px 66px;
		border-left: 2px solid var(--line);
		padding-left: 10px;
	}
	.thread > li {
		border-top: 1px solid var(--line);
	}
	.thread > li:first-child {
		border-top: 0;
	}
	.mail {
		display: flex;
		gap: 8px;
		align-items: baseline;
		width: 100%;
		min-width: 0;
		padding: 4px 0;
		border: 0;
		background: none;
		font: inherit;
		font-size: 0.875rem;
		color: var(--ink);
		text-align: left;
		cursor: pointer;
	}
	.dir {
		color: var(--muted);
	}
	li.sent .dir {
		color: var(--accent);
	}
	.who {
		white-space: nowrap;
		color: var(--muted);
	}
	.first {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.full {
		display: flex;
		flex-direction: column;
		gap: 6px;
		padding: 6px 10px 10px;
		margin-bottom: 6px;
		font-size: 0.875rem;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		background: var(--softer);
		border-radius: 6px;
	}
	.links {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 14px;
		white-space: normal;
	}
	.full :global(.link),
	.link {
		padding: 0;
		border: 0;
		background: none;
		font: inherit;
		font-family: var(--sans);
		font-size: 0.8125rem;
		color: var(--accent);
		text-decoration: underline;
		cursor: pointer;
	}
	.more {
		align-self: flex-start;
		padding: 0;
		border: 0;
		background: none;
		font: inherit;
		font-family: var(--sans);
		font-size: 0.875rem;
		color: var(--accent);
		text-decoration: underline;
		cursor: pointer;
	}
	.warn {
		margin: 0;
		color: var(--warn);
		font-size: 0.875rem;
	}
	@media (max-width: 600px) {
		.who {
			display: none;
		}
		.task,
		.states,
		.thread {
			margin-left: 0;
		}
	}
</style>
