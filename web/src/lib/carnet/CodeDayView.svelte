<script lang="ts">
	// A day of pushed code, as the journal shows it: one line per work item, the rest counted.
	import type { CodeDay } from '../api2.js';

	let { code, day }: { code: CodeDay; day: string } = $props();

	const base = (path: string) => (code.repo ? `https://github.com/${code.repo}/blob/${code.branch ?? 'HEAD'}/${path}` : '');
	let commitsUrl = $derived(
		code.repo
			? `https://github.com/${code.repo}/commits/${code.branch ?? ''}?since=${day}&until=${day}`
			: ''
	);
</script>

<div class="code">
	{#each code.chantiers as c (c.code)}
		<p>
			<a class="item" href={base(c.path)} target="_blank" rel="noopener"><b>{c.code}</b> {c.title}</a>
			<small>— {c.count} commit{c.count > 1 ? 's' : ''}{c.stopped ? ` · arrêté sur : ${c.stopped}` : ''}</small>
		</p>
	{/each}
	{#if code.other}
		<p>
			<small>
				{code.chantiers.length ? '+ ' : ''}{code.other} commit{code.other > 1 ? 's' : ''} sans chantier{#if commitsUrl}
					· <a href={commitsUrl} target="_blank" rel="noopener">voir sur GitHub</a>{/if}
			</small>
		</p>
	{/if}
</div>

<style>
	.code {
		display: flex;
		flex-direction: column;
		gap: 2px;
		font-family: var(--sans);
		font-size: 0.9375rem;
	}
	p {
		margin: 0;
		overflow-wrap: anywhere;
	}
	.item {
		text-decoration: none;
	}
	.item b {
		font-family: ui-monospace, Menlo, Consolas, monospace;
		font-size: 0.875rem;
		color: var(--accent);
	}
	small {
		color: var(--muted);
		font-size: 0.8125rem;
	}
</style>
