<script lang="ts">
	import { v2, type Tag } from '#lib/api2.js';
	import { failure, reload } from '#lib/carnet/state.svelte.js';

	let tags = $state<Tag[] | null>(null);
	let message = $state('');

	$effect(() => {
		v2.tags()
			.then((t) => (tags = t))
			.catch((err) => (message = failure(err, 'Étiquettes non chargées : ')));
	});

	async function pin(tag: Tag) {
		message = '';
		try {
			const saved = await v2.pinTag(tag.id, !tag.pinned);
			tags = (tags ?? []).map((t) => (t.id === tag.id ? { ...t, pinned: saved.pinned } : t));
			reload().catch(() => {});
		} catch (err) {
			message = failure(err, 'Épinglage non modifié : ');
		}
	}
</script>

<svelte:head><title>Étiquettes · P.IGE</title></svelte:head>

<div class="wrap">
	<h1>Étiquettes <small>{tags?.length ?? ''}</small></h1>
	<p class="hint">
		Une étiquette s’ajoute en écrivant <b>#nom</b> dans le journal, ou depuis la fiche d’une personne. Les étiquettes épinglées
		apparaissent dans la colonne de gauche.
	</p>
	{#if message}<p class="message" role="alert">{message}</p>{/if}
	{#if !tags}
		<p class="muted">Chargement…</p>
	{:else}
		<ul>
			{#each tags as tag (tag.id)}
				<li>
					<a href="/etiquettes/{tag.id}"><b class="hash">#</b>{tag.name}</a>
					<small>{tag.uses ? `${tag.uses} utilisation${tag.uses > 1 ? 's' : ''}` : 'inutilisée'}</small>
					<button class="pin" class:on={tag.pinned} aria-pressed={tag.pinned} onclick={() => pin(tag)}>
						{tag.pinned ? 'Épinglée' : 'Épingler'}
					</button>
				</li>
			{:else}
				<li class="muted">Aucune étiquette pour l’instant.</li>
			{/each}
		</ul>
	{/if}
</div>

<style>
	.wrap {
		padding: 22px 32px 48px;
		display: flex;
		flex-direction: column;
		gap: 12px;
		max-width: 720px;
	}
	h1 {
		font-size: 1.875rem;
		margin: 0;
	}
	small,
	.muted,
	.hint {
		font-family: var(--sans);
		font-weight: 400;
		font-size: 0.875rem;
		color: var(--muted);
	}
	.hint {
		margin: 0;
		max-width: 60ch;
	}
	.message {
		margin: 0;
		padding: 8px 12px;
		color: var(--warn);
		background: var(--warn-soft);
		border-radius: 8px;
	}
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
		border-top: var(--rule);
	}
	li {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto auto;
		gap: 14px;
		align-items: center;
		min-height: 44px;
		border-bottom: 1px solid var(--line);
	}
	li a {
		font-weight: 700;
		text-decoration: none;
	}
	.hash {
		color: var(--accent);
	}
	.pin {
		min-height: 30px;
		padding: 0 12px;
		font: inherit;
		font-size: 0.8125rem;
		color: var(--muted);
		background: transparent;
		border: 1px solid var(--line);
		border-radius: 15px;
	}
	.pin.on {
		font-weight: 700;
		color: var(--ink);
		background: var(--soft);
		border-color: var(--accent);
	}
	@media (max-width: 600px) {
		.wrap {
			padding: 16px;
		}
	}
</style>
