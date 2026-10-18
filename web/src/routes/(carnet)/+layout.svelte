<script lang="ts">
	import '@fontsource/newsreader/latin-400.css';
	import '@fontsource/newsreader/latin-400-italic.css';
	import '@fontsource/newsreader/latin-600.css';
	import '#lib/carnet/carnet.css';
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { api, ApiError } from '#lib/api.js';
	import Login from '#lib/carnet/Login.svelte';
	import { carnet, reload, todayIso } from '#lib/carnet/state.svelte.js';

	let { children } = $props();
	let phase = $state<'loading' | 'login' | 'ready' | 'offline'>('loading');

	async function start(): Promise<void> {
		try {
			const session = await api.session();
			if (!session.authenticated) {
				phase = 'login';
				return;
			}
			await reload();
			phase = 'ready';
		} catch (err) {
			if (err instanceof ApiError && err.status === 401) phase = 'login';
			else phase = 'offline';
		}
	}

	onMount(start);

	const path = $derived(page.url.pathname);
</script>

<div class="carnet">
	{#if phase === 'loading'}
		<p class="center">Chargement…</p>
	{:else if phase === 'login'}
		<Login onlogin={start} />
	{:else if phase === 'offline'}
		<div class="center">
			<p>Serveur injoignable. Le feuillet a besoin du réseau pour l’instant.</p>
			<button class="btn" onclick={start}>Réessayer</button>
		</div>
	{:else}
		<div class="shell">
			<aside aria-label="Navigation">
				<a class="brand" href="/journal/{todayIso()}">P.IGE</a>
				<nav aria-label="Vues">
					<a href="/journal/{todayIso()}" aria-current={path.startsWith('/journal') ? 'page' : undefined}>
						<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M5 4h11l3 3v13H5z" /><path d="M8 9h8M8 13h8M8 17h5" /></svg>
						Journal
					</a>
					<span class="soon" title="Bientôt">Tâches</span>
					<span class="soon" title="Bientôt">Personnes</span>
					<span class="soon" title="Bientôt">Agenda</span>
				</nav>
				{#if carnet.tree?.pinned_tags.length}
					<div class="group">
						<span class="label">Étiquettes épinglées</span>
						{#each carnet.tree.pinned_tags as tag (tag.id)}
							<span class="pin"><b aria-hidden="true">#</b>{tag.name}<small>{tag.uses}</small></span>
						{/each}
					</div>
				{/if}
				<div class="group spaces">
					{#each carnet.tree?.spaces ?? [] as space (space.id)}
						<span class="space">{space.name}</span>
						{#each space.projects as project (project.id)}
							<a
								class="project"
								class:sub={project.parent_id}
								href="/projets/{project.id}"
								aria-current={path === `/projets/${project.id}` ? 'page' : undefined}
							>
								<span class="name">{project.name}</span>
								{#if project.team}<span class="team">{project.team}</span>{/if}
								<small>{project.open_tasks || ''}</small>
							</a>
						{/each}
					{/each}
				</div>
				<a class="old" href="/">Écran de saisie actuel</a>
			</aside>
			<main>{@render children()}</main>
		</div>
	{/if}
</div>

<style>
	.center {
		padding: 20vh 24px 0;
		text-align: center;
	}
	.shell {
		display: grid;
		grid-template-columns: 264px minmax(0, 1fr);
		min-height: 100dvh;
	}
	aside {
		position: sticky;
		top: 0;
		height: 100dvh;
		overflow-y: auto;
		box-sizing: border-box;
		padding: 18px 12px;
		display: flex;
		flex-direction: column;
		gap: 14px;
		background: var(--surface);
		border-right: 1px solid var(--line);
	}
	.brand {
		padding: 0 8px;
		font-family: var(--serif);
		font-size: 1.375rem;
		font-weight: 600;
		text-decoration: none;
	}
	nav {
		display: flex;
		flex-direction: column;
		gap: 1px;
	}
	nav a,
	nav .soon {
		display: flex;
		align-items: center;
		gap: 10px;
		min-height: 32px;
		padding: 0 8px;
		border-radius: 8px;
		text-decoration: none;
	}
	nav a[aria-current='page'] {
		font-weight: 700;
		background: var(--soft);
	}
	nav .soon {
		color: var(--muted);
		padding-left: 36px;
		font-size: 0.875rem;
	}
	svg {
		width: 18px;
		height: 18px;
		fill: none;
		stroke: currentColor;
		stroke-width: 2;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
	.group {
		display: flex;
		flex-direction: column;
		gap: 1px;
	}
	.group > .label {
		padding: 0 8px 3px;
	}
	.pin {
		display: flex;
		gap: 6px;
		min-height: 27px;
		align-items: center;
		padding: 0 8px;
		font-size: 0.875rem;
	}
	.pin b {
		color: var(--accent);
	}
	.pin small,
	.project small {
		margin-left: auto;
		color: var(--muted);
		font-variant-numeric: tabular-nums;
	}
	.space {
		margin-top: 8px;
		padding: 0 8px 2px;
		font-family: var(--serif);
		font-weight: 600;
		border-bottom: 1px solid var(--line);
	}
	.project {
		display: flex;
		align-items: center;
		gap: 6px;
		min-height: 28px;
		padding: 0 8px 0 18px;
		border-radius: 6px;
		font-size: 0.875rem;
		text-decoration: none;
	}
	.project.sub {
		padding-left: 34px;
	}
	.project[aria-current='page'] {
		font-weight: 700;
		background: var(--soft);
	}
	.project .name {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.team {
		font-size: 0.6875rem;
		font-weight: 700;
		color: var(--muted);
		border: 1px solid var(--line);
		border-radius: 4px;
		padding: 0 4px;
	}
	.old {
		margin-top: auto;
		padding: 8px;
		font-size: 0.8125rem;
		color: var(--muted);
	}
	main {
		min-width: 0;
	}
	@media (max-width: 760px) {
		.shell {
			grid-template-columns: 1fr;
		}
		aside {
			position: static;
			height: auto;
			border-right: 0;
			border-bottom: 1px solid var(--line);
		}
		.spaces {
			display: none;
		}
	}
</style>
