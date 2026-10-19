<script lang="ts">
	// What a task came from (often a mail filed from Thunderbird): its text, readable anywhere,
	// on the phone as on the site, and a button to reopen the mail when Thunderbird is there.
	import { v2, type Entry } from '../api2.js';
	import { openMail, thunderbird } from './thunderbird.svelte.js';

	let { entryId }: { entryId: string } = $props();

	let entry = $state<Entry | null>(null);
	let missing = $state(false);
	let expanded = $state(false);

	$effect(() => {
		const current = entryId;
		entry = null;
		missing = false;
		expanded = false;
		v2.entry(current)
			.then((e) => {
				if (current === entryId) entry = e;
			})
			.catch(() => {
				if (current === entryId) missing = true;
			});
	});

	const LONG = 700;
	let isMail = $derived(!!entry?.mail_message_id);
	// The first line of a mail is « Mail de … »: shown as the heading, not repeated in the text.
	let lines = $derived(entry ? entry.body.split('\n') : []);
	let sender = $derived(isMail && lines[0]?.startsWith('Mail de ') ? lines[0].slice(8) : '');
	let text = $derived((sender ? lines.slice(1) : lines).join('\n').trim());
	let long = $derived(text.length > LONG);
	let shown = $derived(long && !expanded ? `${text.slice(0, LONG).replace(/\s+\S*$/, '')}…` : text);
	let day = $derived(
		entry ? new Date(`${entry.entry_date}T12:00:00`).toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' }) : ''
	);
</script>

{#if entry}
	<section class="origin" aria-label={isMail ? 'Mail d’origine' : 'Paragraphe d’origine'}>
		<header>
			<span>
				{#if isMail}✉ <b>{entry.title || '(sans objet)'}</b>{#if sender}<small> · de {sender}</small>{/if}{:else}Vient du paragraphe{/if}
				<small> · <a href="/journal/{entry.entry_date}">{day}</a></small>
			</span>
			{#if isMail && thunderbird.available && entry.mail_message_id}
				<button class="btn" onclick={() => entry?.mail_message_id && openMail(entry.mail_message_id)}>Ouvrir dans Thunderbird</button>
			{/if}
		</header>
		{#if text}
			<div class="text">{shown}</div>
			{#if long}
				<button class="plain link" onclick={() => (expanded = !expanded)} aria-expanded={expanded}>
					{expanded ? 'Réduire' : 'Lire tout le mail'}
				</button>
			{/if}
		{:else if isMail}
			<p class="muted">Le texte du mail n’a pas été copié. Range-le à nouveau depuis Thunderbird pour l’ajouter.</p>
		{/if}
	</section>
{:else if missing}
	<p class="muted">Le mail ou le paragraphe d’origine a été supprimé.</p>
{/if}

<style>
	.origin {
		display: flex;
		flex-direction: column;
		gap: 6px;
		padding: 10px 12px;
		background: var(--soft);
		border-radius: 8px;
		min-width: 0;
	}
	header {
		display: flex;
		flex-wrap: wrap;
		gap: 6px 12px;
		align-items: center;
		justify-content: space-between;
	}
	header span {
		min-width: 0;
		overflow-wrap: anywhere;
	}
	small,
	.muted {
		color: var(--muted);
		font-size: 0.875rem;
	}
	.muted {
		margin: 0;
	}
	.text {
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		font-size: 0.9375rem;
		line-height: 1.5;
	}
	.link {
		align-self: flex-start;
		padding: 0;
		background: none;
		border: 0;
		color: var(--accent);
		text-decoration: underline;
		cursor: pointer;
		font: inherit;
		font-size: 0.875rem;
	}
</style>
