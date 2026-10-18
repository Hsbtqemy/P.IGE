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
	// The project list is open on large screens, folded on phones.
	let wide = $state(true);
	onMount(() => {
		const query = matchMedia('(min-width: 761px)');
		wide = query.matches;
		const change = () => (wide = query.matches);
		query.addEventListener('change', change);
		return () => query.removeEventListener('change', change);
	});
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
					<a href="/journee/{todayIso()}" aria-current={path.startsWith('/journee') ? 'page' : undefined}>
						<svg aria-hidden="true" viewBox="0 0 24 24"><circle cx="12" cy="13" r="8" /><path d="M12 9v4l2.5 2.5M9 2h6" /></svg>
						Ma journée
						{#if carnet.timers.length}<span class="running" title="Minuteurs en cours">● {carnet.timers.length}</span>{/if}
					</a>
					<span class="soon" title="Bientôt">Tâches</span>
					<a href="/personnes" aria-current={path.startsWith('/personnes') ? 'page' : undefined}>
						<svg aria-hidden="true" viewBox="0 0 24 24"><circle cx="9" cy="8" r="3.5" /><path d="M2.5 20c.6-3.6 3.2-5.5 6.5-5.5s5.9 1.9 6.5 5.5M16 4.8a3.5 3.5 0 0 1 0 6.4M18.5 14.8c1.7.8 2.7 2.5 3 5.2" /></svg>
						Personnes
					</a>
					<a href="/etiquettes" aria-current={path.startsWith('/etiquettes') ? 'page' : undefined}>
						<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M5 9h14M5 15h14M10 4 8 20M16 4l-2 16" /></svg>
						Étiquettes
					</a>
					<span class="soon" title="Bientôt">Agenda</span>
				</nav>
				{#if carnet.tree?.pinned_tags.length}
					<div class="group">
						<span class="label">Étiquettes épinglées</span>
						{#each carnet.tree.pinned_tags as tag (tag.id)}
							<a class="pin" href="/etiquettes/{tag.id}" aria-current={path === `/etiquettes/${tag.id}` ? 'page' : undefined}><b aria-hidden="true">#</b>{tag.name}<small>{tag.uses}</small></a>
						{/each}
					</div>
				{/if}
				<details class="group spaces" open={wide}>
					<summary class="label">Espaces et projets</summary>
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
				</details>
				<a class="old" href="/">Écran de saisie actuel</a>
			</aside>
			<main>{@render children()}</main>
		</div>
		{#if carnet.needsLogin}
			<div class="overlay" role="dialog" aria-modal="true" aria-label="Reconnexion">
				<Login
					onlogin={() => {
						carnet.needsLogin = false;
						void reload();
					}}
				/>
			</div>
		{/if}
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
		font-size: 0.875rem;
		text-decoration: none;
	}
	nav a[aria-current='page'] {
		font-weight: 700;
		background: var(--soft);
	}
	.running {
		margin-left: auto;
		font-size: 0.75rem;
		font-weight: 700;
		color: var(--accent);
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
	.pin {
		text-decoration: none;
		border-radius: 6px;
	}
	.pin[aria-current='page'] {
		font-weight: 700;
		background: var(--soft);
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
	.spaces summary {
		padding: 0 8px;
		cursor: pointer;
		list-style: none;
	}
	@media (min-width: 761px) {
		.spaces summary {
			display: none;
		}
	}
	.overlay {
		position: fixed;
		inset: 0;
		z-index: 10;
		background: rgb(30 35 32 / 0.35);
	}
	.space {
		display: block;
		margin-top: 12px;
		padding: 0 8px 2px;
		font-size: 0.8125rem;
		font-weight: 700;
		letter-spacing: 0.01em;
	}
	.space:first-of-type {
		margin-top: 4px;
	}
	.project {
		display: flex;
		align-items: center;
		gap: 6px;
		min-height: 28px;
		padding: 0 8px 0 16px;
		border-radius: 6px;
		font-size: 0.8125rem;
		color: var(--muted);
		text-decoration: none;
	}
	.project:hover {
		color: var(--ink);
	}
	.project.sub {
		padding-left: 30px;
	}
	.project[aria-current='page'] {
		color: var(--ink);
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
		nav .soon {
			display: none;
		}
	}
</style>
