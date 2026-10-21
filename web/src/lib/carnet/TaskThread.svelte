<script lang="ts">
	// A task's story: the mail (or paragraph) it came from, then its follow-up in date order:
	// notes added by hand and « Échange du … » entries grouping the mails of one day (replies
	// sent from Thunderbird, mails kept), each removable, with a synthesis written above.
	import { ApiError } from '../api.js';
	import { v2, type Entry, type TaskMail } from '../api2.js';
	import TaskOrigin from './TaskOrigin.svelte';
	import { failure, longDate, todayIso } from './state.svelte.js';

	let { taskId, originEntryId }: { taskId: string; originEntryId: string | null | undefined } = $props();

	let entries = $state<Entry[]>([]);
	let mails = $state<TaskMail[]>([]);
	let loaded = $state(false);
	let message = $state('');
	let draft = $state('');
	let adding = $state(false);
	let open = $state(new Set<string>()); // mails unfolded
	let editing = $state<string | null>(null);
	let synthesis = $state('');

	async function load(current = taskId) {
		try {
			const [e, m] = await Promise.all([v2.timeline({ task_id: current, limit: 200 }), v2.taskMails(current)]);
			if (current !== taskId) return;
			entries = e.filter((x) => x.id !== originEntryId).reverse(); // oldest first
			mails = m;
		} catch (err) {
			message = failure(err, 'Suivi non chargé : ');
		} finally {
			loaded = true;
		}
	}

	$effect(() => {
		const current = taskId;
		entries = [];
		mails = [];
		loaded = false;
		void load(current);
	});

	const mailsOf = (entryId: string) => mails.filter((m) => m.entry_id === entryId);
	const clock = (iso: string) => new Date(iso).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
	const firstLine = (text: string) => text.split('\n').find((l) => l.trim())?.trim() ?? '';

	async function addFollowUp(event: SubmitEvent) {
		event.preventDefault();
		const body = draft.trim();
		if (!body) return;
		adding = true;
		message = '';
		try {
			await v2.addFollowUp(taskId, todayIso(), body);
			draft = '';
			await load();
		} catch (err) {
			message = failure(err, 'Suivi non ajouté : ');
		} finally {
			adding = false;
		}
	}

	async function removeMail(m: TaskMail) {
		if (!confirm(`Retirer ce mail du suivi ?${m.subject ? ` (« ${m.subject} »)` : ''}`)) return;
		message = '';
		try {
			await v2.deleteTaskMail(m.id);
			await load();
		} catch (err) {
			message = failure(err, 'Mail non retiré : ');
		}
	}

	function startSynthesis(e: Entry) {
		editing = e.id;
		synthesis = e.body;
	}

	async function saveSynthesis(e: Entry) {
		message = '';
		try {
			await v2.updateEntry(e.id, { expected_revision: e.revision, body: synthesis.trim() });
			editing = null;
			await load();
		} catch (err) {
			message =
				err instanceof ApiError && err.status === 409 ? 'Modifié ailleurs entre-temps : recharge la page.' : failure(err, 'Non enregistré : ');
		}
	}
</script>

<div class="thread">
	{#if originEntryId}<TaskOrigin entryId={originEntryId} />{/if}

	<section class="follow" aria-label="Suivi de la tâche">
		<span class="label">Suivi {#if entries.length}<small>{entries.length}</small>{/if}</span>
		{#if message}<p class="warn" role="alert">{message}</p>{/if}
		{#each entries as e (e.id)}
			{@const own = mailsOf(e.id)}
			<article class="item">
				<header>
					<a href="/journal/{e.entry_date}#e-{e.id}">{longDate(e.entry_date)}</a>
					{#if own.length}<b>{e.title.replace(/^Échange du [^—]+— ?/, '') || 'Échange'}</b>{:else if e.title}<b>{e.title}</b>{/if}
				</header>
				{#if editing === e.id}
					<textarea bind:value={synthesis} rows="3" placeholder="En quelques mots : où en est l’échange ?" aria-label="Synthèse"></textarea>
					<div class="row">
						<button class="btn primary" onclick={() => saveSynthesis(e)}>Enregistrer</button>
						<button class="btn" onclick={() => (editing = null)}>Annuler</button>
					</div>
				{:else if e.body.trim()}
					<p class="body">{e.body}</p>
				{/if}
				{#if own.length}
					{#if editing !== e.id}
						<button class="link" onclick={() => startSynthesis(e)}>{e.body.trim() ? 'Modifier la synthèse' : '+ Résumer l’échange'}</button>
					{/if}
					<ul class="mails">
						{#each own as m (m.id)}
							<li class:sent={m.direction === 'sent'}>
								<button class="mail" onclick={() => (open = open.has(m.id) ? new Set([...open].filter((x) => x !== m.id)) : new Set([...open, m.id]))} aria-expanded={open.has(m.id)}>
									<span class="dir" title={m.direction === 'sent' ? 'Envoyé' : 'Reçu'}>{m.direction === 'sent' ? '↗' : '↙'}</span>
									<span class="when">{clock(m.sent_at)}</span>
									<span class="who">{m.direction === 'sent' ? `à ${m.recipients || '—'}` : `de ${m.author || '—'}`}</span>
									<span class="first">{firstLine(m.body)}</span>
								</button>
								<button class="x" onclick={() => removeMail(m)} aria-label="Retirer ce mail du suivi" title="Retirer du suivi">×</button>
								{#if open.has(m.id)}
									<div class="full">
										{#if m.body.trim()}{m.body}{:else}<em>(texte non copié)</em>{/if}
										{#if m.attachments}<small>Pièces jointes : {m.attachments}</small>{/if}
									</div>
								{/if}
							</li>
						{/each}
					</ul>
				{/if}
			</article>
		{:else}
			{#if loaded}<p class="muted">Rien encore. Tes réponses envoyées depuis Thunderbird s’ajouteront ici ; tu peux aussi noter un suivi.</p>{/if}
		{/each}
		<form class="add" onsubmit={addFollowUp}>
			<textarea bind:value={draft} rows="2" placeholder="Ajouter un suivi : répondu, relancé, décidé…" aria-label="Ajouter un suivi"
				onkeydown={(ev) => {
					if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) (ev.currentTarget as HTMLTextAreaElement).form?.requestSubmit();
				}}></textarea>
			<button class="btn" disabled={adding || !draft.trim()}>Ajouter</button>
		</form>
	</section>
</div>

<style>
	.thread,
	.follow {
		display: flex;
		flex-direction: column;
		gap: 8px;
		min-width: 0;
	}
	.label {
		font-size: 0.8125rem;
		font-weight: 700;
		color: var(--muted);
	}
	.item {
		display: flex;
		flex-direction: column;
		gap: 4px;
		padding: 6px 0 6px 12px;
		border-left: 2px solid var(--line);
	}
	header {
		display: flex;
		flex-wrap: wrap;
		gap: 2px 10px;
		align-items: baseline;
		font-size: 0.875rem;
	}
	header a {
		color: var(--muted);
		font-size: 0.8125rem;
	}
	.body {
		margin: 0;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}
	.mails {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.mails li {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		align-items: start;
		border-top: 1px solid var(--line);
	}
	.mail {
		display: flex;
		gap: 8px;
		align-items: baseline;
		min-width: 0;
		padding: 4px 0;
		background: none;
		border: 0;
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
	.when {
		font-family: ui-monospace, Menlo, Consolas, monospace;
		font-size: 0.75rem;
		color: var(--muted);
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
	.x {
		width: 24px;
		height: 24px;
		border: 0;
		background: none;
		color: var(--muted);
		cursor: pointer;
	}
	.x:hover {
		color: var(--warn);
	}
	.full {
		grid-column: 1 / -1;
		display: flex;
		flex-direction: column;
		gap: 4px;
		padding: 6px 10px 10px;
		font-size: 0.875rem;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		background: var(--softer);
		border-radius: 6px;
	}
	small,
	.muted {
		color: var(--muted);
		font-size: 0.8125rem;
		font-weight: 400;
	}
	.muted {
		margin: 0;
	}
	.link {
		align-self: flex-start;
		padding: 0;
		background: none;
		border: 0;
		font: inherit;
		font-size: 0.8125rem;
		color: var(--accent);
		text-decoration: underline;
		cursor: pointer;
	}
	textarea {
		width: 100%;
		font: inherit;
		font-size: 0.9375rem;
		padding: 6px 8px;
		color: var(--ink);
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 6px;
	}
	.add {
		display: flex;
		gap: 6px;
		align-items: flex-end;
	}
	.row {
		display: flex;
		gap: 6px;
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
	}
</style>
