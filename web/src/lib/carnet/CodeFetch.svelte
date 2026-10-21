<script lang="ts">
	// « Récupérer le code »: read every linked repository now (end of the day, end of a
	// piece of work), then the day's code entries are in the journal, ready to comment.
	// Otherwise the server reads them on its own at 12:30 and 19:30.
	import { v2 } from '../api2.js';
	import { failure } from './state.svelte.js';

	let { onfetched }: { onfetched: () => void } = $props();

	let repos = $state<{ repo: string; last_sync: string | null; last_error: string | null }[]>([]);
	let busy = $state(false);
	let message = $state('');

	async function load() {
		try {
			repos = await v2.linkedRepos();
		} catch {
			repos = [];
		}
	}

	$effect(() => {
		void load();
	});

	let last = $derived(
		repos
			.map((r) => r.last_sync)
			.filter((x): x is string => !!x)
			.sort()
			.at(-1)
	);

	async function fetchNow() {
		busy = true;
		message = '';
		try {
			const r = await v2.syncAllCode();
			message = r.errors.length
				? `${r.errors[0].repo} : ${r.errors[0].error}`
				: r.days
					? `${r.days} jour${r.days > 1 ? 's' : ''} de code mis à jour.`
					: 'Rien de nouveau.';
			await load();
			onfetched();
		} catch (err) {
			message = failure(err, 'Code non récupéré : ');
		} finally {
			busy = false;
		}
	}

	const clock = (iso: string) =>
		new Date(iso).toLocaleString('fr-FR', { weekday: 'short', hour: '2-digit', minute: '2-digit' });
</script>

{#if repos.length}
	<div class="fetch">
		<span class="label">Code <small>{repos.length} dépôt{repos.length > 1 ? 's' : ''}</small></span>
		<button class="btn" disabled={busy} onclick={fetchNow}>{busy ? 'Lecture…' : '↻ Récupérer le code'}</button>
		<small>{last ? `lu ${clock(last)}` : 'jamais lu'} · sinon à 12 h 30 et 19 h 30</small>
		{#if message}<small class="msg" role="status">{message}</small>{/if}
	</div>
{/if}

<style>
	.fetch {
		display: flex;
		flex-direction: column;
		gap: 4px;
		align-items: flex-start;
	}
	.label {
		font-size: 0.75rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--muted);
	}
	small {
		color: var(--muted);
		font-size: 0.8125rem;
		font-weight: 400;
		text-transform: none;
		letter-spacing: 0;
	}
	.msg {
		color: var(--ink);
	}
</style>
