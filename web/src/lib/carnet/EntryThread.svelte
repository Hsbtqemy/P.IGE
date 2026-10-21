<script lang="ts">
	// A thread of journal entries in full (a project's, a person's, a tag's…), newest first,
	// with a date between days; each one editable in place and linked to its day.
	import { ApiError } from '../api.js';
	import { v2, type Entry } from '../api2.js';
	import { segments } from '../feuillet.js';
	import MailOpen from './MailOpen.svelte';
	import { failure, longDate, placeName } from './state.svelte.js';

	let { entries, showPlace = true, onchanged }: { entries: Entry[]; showPlace?: boolean; onchanged?: (e: Entry) => void } = $props();

	const FOLD = 600;
	let unfolded = $state(new Set<string>());
	let editing = $state<string | null>(null);
	let draft = $state('');
	let saving = $state(false);
	let message = $state('');

	let days = $derived.by(() => {
		const out: { day: string; list: Entry[] }[] = [];
		for (const e of entries) {
			const last = out.at(-1);
			if (last?.day === e.entry_date) last.list.push(e);
			else out.push({ day: e.entry_date, list: [e] });
		}
		return out;
	});

	function lines(e: Entry): string[] {
		const long = e.body.length > FOLD && !unfolded.has(e.id);
		const text = long ? `${e.body.slice(0, FOLD).replace(/\s+\S*$/, '')} …` : e.body;
		return text.split('\n');
	}

	function edit(e: Entry) {
		editing = e.id;
		draft = e.body;
		message = '';
	}

	async function save(e: Entry) {
		saving = true;
		message = '';
		try {
			const updated = await v2.updateEntry(e.id, { expected_revision: e.revision, body: draft });
			editing = null;
			onchanged?.(updated);
		} catch (err) {
			message =
				err instanceof ApiError && err.status === 409
					? 'Ce paragraphe a été modifié ailleurs entre-temps : recharge la page.'
					: failure(err, 'Paragraphe non enregistré : ');
		} finally {
			saving = false;
		}
	}

	const time = (e: Entry) => [e.start_time, e.end_time].filter(Boolean).join('–');
</script>

{#each days as d (d.day)}
	<section class="day" aria-label={longDate(d.day)}>
		<h2><a href="/journal/{d.day}">{longDate(d.day)}</a></h2>
		{#each d.list as e (e.id)}
			<article class="entry" class:decision={e.kind === 'decision'}>
				<header>
					{#if time(e)}<span class="time">{time(e)}</span>{/if}
					{#if e.kind === 'meeting'}<span class="kind">Réunion</span>{/if}
					{#if e.kind === 'decision'}<span class="kind decision">Décision{e.decision_applied ? ' appliquée' : ''}</span>{/if}
					{#if e.source === 'mail'}<span class="kind mail">Mail</span>{/if}
					{#if e.title}<b>{e.title}</b>{/if}
					<span class="grow"></span>
					{#if showPlace}<small>{placeName(e)}</small>{/if}
				</header>
				{#if e.source === 'writing'}
					<p><a href="/ecrire/{e.id}">Texte long, {e.body.split(/\s+/).filter(Boolean).length} mots · ouvrir dans l’éditeur →</a></p>
				{:else if editing === e.id}
					<textarea bind:value={draft} rows={Math.min(20, Math.max(4, draft.split('\n').length + 1))} aria-label="Texte du paragraphe"></textarea>
					{#if message}<p class="warn" role="alert">{message}</p>{/if}
					<div class="actions">
						<button class="btn primary" disabled={saving} onclick={() => save(e)}>Enregistrer</button>
						<button class="btn" onclick={() => (editing = null)}>Annuler</button>
					</div>
				{:else}
					<div class="body">
						{#each lines(e) as line, i (i)}
							{#if line.trim()}
								<p>
									{#each segments(line) as seg, j (j)}
										{#if seg.type === 'person'}<span class="chip-person">{seg.text}</span
											>{:else if seg.type === 'tag'}<span class="chip-tag">{seg.text}</span
											>{:else if seg.type === 'decision'}<span class="kind decision">DÉCISION</span
											>{:else if seg.type === 'task'}<span class="task">☐ {seg.text}</span
											>{:else}{seg.text}{/if}
									{/each}
								</p>
							{/if}
						{/each}
					</div>
					<footer>
						{#if e.body.length > FOLD}
							<button class="link" onclick={() => (unfolded = new Set([...unfolded, e.id]))} hidden={unfolded.has(e.id)}>Lire la suite</button>
						{/if}
						{#if e.mail_message_id}<MailOpen messageId={e.mail_message_id} class="link" label="Ouvrir le mail" />{/if}
						{#if e.task_id}<a class="link" href="{e.project_id ? `/projets/${e.project_id}` : `/espaces/${e.space_id}`}?tache={e.task_id}">{e.source === 'mail' ? 'Voir l’échange dans la tâche' : 'Voir la tâche'}</a>{/if}
						<button class="link" onclick={() => edit(e)}>Modifier</button>
						<a class="link" href="/journal/{e.entry_date}#e-{e.id}">Dans le journal du jour</a>
					</footer>
				{/if}
			</article>
		{/each}
	</section>
{/each}

<style>
	.day {
		display: flex;
		flex-direction: column;
		gap: 10px;
	}
	h2 {
		margin: 8px 0 0;
		font-size: 1.125rem;
		padding-bottom: 4px;
		border-bottom: var(--rule);
	}
	h2 a {
		text-decoration: none;
	}
	.entry {
		display: flex;
		flex-direction: column;
		gap: 6px;
		padding: 10px 0 10px 14px;
		border-left: var(--margin);
	}
	.entry.decision {
		border-left-color: var(--decision);
	}
	header {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 10px;
		align-items: baseline;
	}
	.grow {
		flex: 1;
	}
	.time {
		font-family: ui-monospace, Menlo, Consolas, monospace;
		font-size: 0.8125rem;
		color: var(--muted);
	}
	.kind {
		font-size: 0.6875rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--accent);
	}
	.kind.decision {
		color: var(--decision);
	}
	.kind.mail {
		color: var(--muted);
	}
	small {
		color: var(--muted);
		font-size: 0.8125rem;
	}
	.body p,
	p {
		margin: 0 0 4px;
		line-height: 1.55;
		overflow-wrap: anywhere;
	}
	.chip-person,
	.chip-tag {
		padding: 0 4px;
		border-radius: 4px;
		background: var(--chip);
	}
	.task {
		color: var(--accent);
	}
	footer {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 14px;
	}
	footer :global(.link),
	.link {
		padding: 0;
		background: none;
		border: 0;
		font: inherit;
		font-size: 0.8125rem;
		color: var(--muted);
		text-decoration: underline;
		cursor: pointer;
	}
	footer :global(.link:hover),
	.link:hover {
		color: var(--accent);
	}
	textarea {
		width: 100%;
		font: inherit;
		line-height: 1.55;
		padding: 8px;
		color: var(--ink);
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 8px;
	}
	.actions {
		display: flex;
		gap: 6px;
	}
	.warn {
		color: var(--warn);
		font-size: 0.875rem;
	}
</style>
