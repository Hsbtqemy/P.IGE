<script lang="ts">
	// The mails of a project (or of a space without project), by conversation: everything of an
	// exchange together, wherever it was kept (filed in the journal, or in a task's follow-up).
	// A click unfolds the thread, readable without Thunderbird.
	import { tick } from 'svelte';
	import { page } from '$app/state';
	import { v2, type Conversation, type ConversationMail, type ConversationState } from '../api2.js';
	import MailOpen from './MailOpen.svelte';
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
		void load('');
	});

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

	const date = (iso: string) => new Date(iso.length > 10 ? iso : `${iso}T12:00:00`).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' });
	const firstLine = (text: string) => text.split('\n').find((l) => l.trim())?.trim() ?? '';
	let shown = $derived(list ? (showAll || query.trim() ? list : list.slice(0, FIRST)) : []);
</script>

<section class="mails" aria-labelledby="mails-title">
	<h2 id="mails-title">
		Mails <small>{list ? `${list.length} conversation${list.length > 1 ? 's' : ''}` : ''}</small>
	</h2>
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
											{#if m.attachments}<small>Pièces jointes : {m.attachments}</small>{/if}
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
		.thread {
			margin-left: 0;
		}
	}
</style>
