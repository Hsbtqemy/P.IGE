<script lang="ts">
	// Mails waiting for a reply (« À répondre » from Thunderbird, or set in P.IGE), whatever the
	// day: they stay until answered or put away. Replying from Thunderbird clears them by itself.
	// Below, the exchanges where you wait for their answer.
	import { v2, type Conversation, type ConversationState } from '../api2.js';
	import MailOpen from './MailOpen.svelte';
	import { failure, placeName } from './state.svelte.js';

	let { refreshKey = 0, onchanged }: { refreshKey?: number; onchanged?: () => void } = $props();

	let list = $state<Conversation[]>([]);
	let message = $state('');
	let busy = $state<string | null>(null);

	async function load() {
		try {
			list = await v2.conversations({ state: 'to_answer,waiting', limit: 100 });
		} catch (err) {
			message = failure(err, 'Mails à répondre non chargés : ');
		}
	}

	$effect(() => {
		void refreshKey;
		void load();
	});

	async function set(c: Conversation, state: ConversationState) {
		busy = c.id;
		message = '';
		try {
			await v2.setConversationState(c.id, state);
			await load();
			onchanged?.();
		} catch (err) {
			message = failure(err, 'Non modifié : ');
		} finally {
			busy = null;
		}
	}

	function since(iso: string): string {
		const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
		return days < 1 ? 'aujourd’hui' : days === 1 ? 'depuis hier' : `depuis ${days} j`;
	}
	/** A mail to answer waits since it came (its last mail received), not since it was filed. */
	const waitingSince = (c: Conversation) => (c.last?.direction === 'received' && c.last.at < c.state_since ? c.last.at : c.state_since);
	const href = (c: Conversation) => `${c.project_id ? `/projets/${c.project_id}` : `/espaces/${c.space_id}`}?conv=${c.id}`;

	let toAnswer = $derived(list.filter((c) => c.state === 'to_answer').sort((a, b) => a.state_since.localeCompare(b.state_since)));
	let waiting = $derived(list.filter((c) => c.state === 'waiting').sort((a, b) => a.state_since.localeCompare(b.state_since)));
</script>

{#if toAnswer.length || waiting.length || message}
	<section class="answer" aria-labelledby="answer-title">
		<h2 id="answer-title">Mails à répondre <small>{toAnswer.length || ''}</small></h2>
		{#if message}<p class="warn" role="alert">{message}</p>{/if}
		{#each toAnswer as c (c.id)}
			<div class="row">
				<span class="what">
					<a href={href(c)}><b>{c.subject || '(sans objet)'}</b></a>
					<small>{c.people.join(', ') || '—'} · {placeName(c)} · <span class:old={Date.now() - new Date(waitingSince(c)).getTime() > 3 * 86_400_000}>{since(waitingSince(c))}</span></small>
				</span>
				<span class="tools">
					{#if c.last_received}<MailOpen messageId={c.last_received} class="tool" label="Ouvrir" />{/if}
					<button class="tool" disabled={busy === c.id} onclick={() => set(c, 'answered')} title="Déjà répondu (ailleurs que depuis Thunderbird)">Répondu</button>
					<button class="tool" disabled={busy === c.id} onclick={() => set(c, 'waiting')} title="Tu as répondu et tu attends leur réponse">J’attends</button>
					<button class="tool" disabled={busy === c.id} onclick={() => set(c, 'filed')} title="Rien à répondre : le ranger">Classer</button>
				</span>
			</div>
		{/each}
		{#if waiting.length}
			<h3>J’attends une réponse <small>{waiting.length}</small></h3>
			{#each waiting as c (c.id)}
				<div class="row waiting">
					<span class="what">
						<a href={href(c)}>{c.subject || '(sans objet)'}</a>
						<small>{c.people.join(', ') || '—'} · {placeName(c)} · {since(c.state_since)}</small>
					</span>
					<span class="tools">
						<button class="tool" disabled={busy === c.id} onclick={() => set(c, 'to_answer')} title="Il faut relancer : remettre à répondre">Relancer</button>
						<button class="tool" disabled={busy === c.id} onclick={() => set(c, 'filed')} title="C’est réglé : le ranger">Classer</button>
					</span>
				</div>
			{/each}
		{/if}
	</section>
{/if}

<style>
	.answer {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	h3 {
		margin: 10px 0 2px;
		font-family: var(--sans);
		font-size: 0.75rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--muted);
	}
	small {
		font-family: var(--sans);
		font-weight: 400;
		color: var(--muted);
		font-size: 0.8125rem;
	}
	.row {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 12px;
		align-items: baseline;
		justify-content: space-between;
		padding: 6px 0 6px 12px;
		border-left: 3px solid var(--warn);
		border-bottom: 1px solid var(--line);
	}
	.row.waiting {
		border-left-color: var(--line);
	}
	.what {
		display: flex;
		flex-direction: column;
		gap: 1px;
		min-width: 0;
		flex: 1;
		overflow-wrap: anywhere;
	}
	.what a {
		color: var(--ink);
		text-decoration: none;
	}
	.what a:hover {
		text-decoration: underline;
	}
	.old {
		color: var(--warn);
	}
	.tools {
		display: inline-flex;
		flex-wrap: wrap;
		gap: 2px 10px;
	}
	.tools :global(.tool),
	.tool {
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
	.warn {
		margin: 0;
		color: var(--warn);
		font-size: 0.875rem;
	}
</style>
