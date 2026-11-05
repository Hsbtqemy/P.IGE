<script lang="ts">
	// A mail's attachments kept in P.IGE: links to download them (never shown in the page).
	type Kept = { id: string; kind?: string; name: string; size?: number; url: string };
	let { files }: { files: Kept[] } = $props();
	let kept = $derived(files.filter((f) => f.kind === 'attachment'));
	const size = (n = 0) => (n < 1024 ? `${n} o` : n < 1024 * 1024 ? `${Math.round(n / 1024)} Ko` : `${(n / 1024 / 1024).toLocaleString('fr-FR', { maximumFractionDigits: 1 })} Mo`);
</script>

{#if kept.length}
	<span class="files">
		{#each kept as f (f.id)}
			<a href={f.url} download={f.name} title="Télécharger">📎 {f.name} <small>{size(f.size)}</small></a>
		{/each}
	</span>
{/if}

<style>
	.files {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 14px;
		font-family: var(--sans);
		font-size: 0.8125rem;
		white-space: normal;
	}
	a {
		color: var(--accent);
	}
	small {
		color: var(--muted);
	}
</style>
