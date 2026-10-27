<script lang="ts">
	// A long text (written in « Écrire ») read where it sits in the journal: formatted, folded
	// when long, with a link to the editor.
	import type { Entry } from '../api2.js';
	import { toHtml } from './writing/export.js';
	import { showRange } from './timerange.js';

	let { entry, heading = true }: { entry: Entry; heading?: boolean } = $props();
	let open = $state(false);

	// A first « # Title » that repeats the title is not shown twice.
	let body = $derived.by(() => {
		const lines = entry.body.split('\n');
		const first = lines.findIndex((l) => l.trim());
		const m = first >= 0 ? lines[first].match(/^#\s+(.+?)\s*#*\s*$/) : null;
		if (m && entry.title && m[1].trim().toLowerCase() === entry.title.trim().toLowerCase()) lines.splice(first, 1);
		return lines.join('\n');
	});
	let words = $derived(entry.body.split(/\s+/).filter((w) => /[\p{L}\p{N}]/u.test(w)).length);
	let long = $derived(body.length > 1500 || body.split('\n').length > 24);
	let html = $derived(toHtml(body, true));
</script>

<div class="writing">
	<p class="head">
		{#if heading}<b>{entry.title || 'Texte'}</b>{/if}
		<small>{heading ? '· ' : 'Texte long, '}{words} mots</small>
		<a href="/ecrire/{entry.id}">Ouvrir dans l’éditeur →</a>
	</p>
	{#if entry.about}
		{@const a = entry.about}
		<p class="about">
			Notes de <a href={a.kind === 'event' ? `/agenda/${a.day}` : `/journal/${a.day}#e-${a.entry_id}`}>{a.title}</a>{#if a.start_time}{' · '}{showRange(a.start_time, a.end_time)}{/if}{#if a.location}{' · '}{a.location}{/if}
		</p>
	{/if}
	<!-- eslint-disable-next-line svelte/no-at-html-tags -- sanitised by DOMPurify in toHtml -->
	<div class="rendered" class:folded={long && !open}>{@html html}</div>
	{#if long}
		<button class="more" onclick={() => (open = !open)} aria-expanded={open}>{open ? 'Replier' : 'Lire tout'}</button>
	{/if}
</div>

<style>
	.writing {
		display: flex;
		flex-direction: column;
		gap: 4px;
		min-width: 0;
	}
	.head {
		display: flex;
		flex-wrap: wrap;
		gap: 2px 8px;
		align-items: baseline;
		margin: 0;
	}
	.head small {
		color: var(--muted);
		font-family: var(--sans);
		font-size: 0.8125rem;
	}
	.head a {
		margin-left: auto;
		font-family: var(--sans);
		font-size: 0.8125rem;
	}
	.about {
		margin: 0;
		font-family: var(--sans);
		font-size: 0.8125rem;
		color: var(--muted);
	}
	.rendered {
		position: relative;
		overflow-wrap: anywhere;
		line-height: 1.55;
	}
	.rendered.folded {
		max-height: 22em;
		overflow: hidden;
	}
	.rendered.folded::after {
		content: '';
		position: absolute;
		left: 0;
		right: 0;
		bottom: 0;
		height: 4em;
		background: linear-gradient(transparent, var(--surface));
	}
	.rendered :global(h1),
	.rendered :global(h2),
	.rendered :global(h3) {
		margin: 0.8em 0 0.3em;
		line-height: 1.25;
	}
	.rendered :global(h1) {
		font-size: 1.35rem;
	}
	.rendered :global(h2) {
		font-size: 1.15rem;
	}
	.rendered :global(h3) {
		font-size: 1rem;
	}
	.rendered :global(p) {
		margin: 0.4em 0;
	}
	.rendered :global(ul),
	.rendered :global(ol) {
		margin: 0.3em 0;
		padding-left: 1.4em;
	}
	.rendered :global(li:has(> input[type='checkbox'])) {
		list-style: none;
		margin-left: -1.3em;
	}
	.rendered :global(input[type='checkbox']) {
		margin: 0 0.45em 0 0;
		accent-color: var(--accent);
		vertical-align: -0.1em;
	}
	.rendered :global(li:has(> input:checked)) {
		color: var(--muted);
		text-decoration: line-through;
	}
	.rendered :global(blockquote) {
		margin: 0.4em 0;
		padding-left: 0.9em;
		border-left: 3px solid var(--accent);
		color: var(--muted);
	}
	.rendered :global(code) {
		font-family: ui-monospace, Menlo, Consolas, monospace;
		font-size: 0.9em;
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
</style>
