<script lang="ts">
	// A paragraph's pictures: thumbnails (a click opens the full image). While editing, each can
	// be removed, and « 🖼 Image » adds more (or pasting one into the text).
	import { deleteImage, uploadImage } from './images.js';
	import { failure } from './state.svelte.js';

	import type { FileRef } from '../api2.js';
	type Img = FileRef;

	let {
		files,
		entryId,
		editable = false,
		onchanged
	}: { files: Img[]; entryId?: string; editable?: boolean; onchanged?: (files: Img[]) => void } = $props();

	// A mail's attachments are listed apart (links), only images are shown here.
	let images = $derived(files.filter((f) => f.kind !== 'attachment'));
	let others = $derived(files.filter((f) => f.kind === 'attachment'));

	let busy = $state(0);
	let message = $state('');
	let picker: HTMLInputElement | undefined = $state();

	export async function add(chosen: File[]) {
		message = '';
		const added: Img[] = [];
		busy += chosen.length;
		for (const file of chosen) {
			try {
				added.push(await uploadImage(file, entryId));
			} catch (err) {
				message = failure(err, 'Image non envoyée : ');
			} finally {
				busy -= 1;
			}
		}
		if (added.length) onchanged?.([...files, ...added]);
	}

	async function remove(img: Img) {
		if (!confirm(`Retirer l’image « ${img.name || 'sans nom'} » ?`)) return;
		try {
			await deleteImage(img.id);
			onchanged?.([...images.filter((f) => f.id !== img.id), ...others]);
		} catch (err) {
			message = failure(err, '');
		}
	}
</script>

{#if images.length || editable}
	<div class="images">
		{#each images as img (img.id)}
			<span class="thumb">
				<a href={img.url} target="_blank" rel="noopener" title={img.name}>
					<img src={img.url} alt={img.name} loading="lazy" width={img.width ?? undefined} height={img.height ?? undefined} />
				</a>
				{#if editable}<button class="x" onclick={() => remove(img)} aria-label="Retirer l’image {img.name}">×</button>{/if}
			</span>
		{/each}
		{#if editable}
			<button class="add" disabled={busy > 0} onclick={() => picker?.click()} title="Joindre des images (ou colle-les dans le texte)">
				{busy ? 'Envoi…' : '🖼 Image'}
			</button>
			<input bind:this={picker} type="file" accept="image/*" multiple hidden
				onchange={(e) => {
					const input = e.currentTarget as HTMLInputElement;
					const chosen = [...(input.files ?? [])];
					input.value = '';
					if (chosen.length) void add(chosen);
				}} />
		{/if}
		{#if message}<small class="warn" role="alert">{message}</small>{/if}
	</div>
{/if}

<style>
	.images {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		align-items: center;
		margin: 6px 0;
	}
	.thumb {
		position: relative;
	}
	.thumb img {
		display: block;
		width: auto;
		height: 120px;
		max-width: 240px;
		object-fit: cover;
		border-radius: 6px;
		border: 1px solid var(--line);
		background: var(--softer);
	}
	.x {
		position: absolute;
		top: 4px;
		right: 4px;
		width: 22px;
		height: 22px;
		padding: 0;
		border: 0;
		border-radius: 50%;
		background: rgba(0, 0, 0, 0.55);
		color: #fff;
		cursor: pointer;
		line-height: 1;
	}
	.add {
		padding: 4px 10px;
		border: 1px dashed var(--line);
		border-radius: 6px;
		background: none;
		font: inherit;
		font-family: var(--sans);
		font-size: 0.8125rem;
		color: var(--muted);
		cursor: pointer;
	}
	.add:hover {
		color: var(--accent);
		border-color: var(--accent);
	}
	.warn {
		flex-basis: 100%;
		font-family: var(--sans);
		color: var(--warn);
		font-size: 0.8125rem;
	}
</style>
