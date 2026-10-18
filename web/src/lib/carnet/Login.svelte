<script lang="ts">
	import { api, ApiError } from '../api.js';

	let { onlogin }: { onlogin: () => void } = $props();
	let password = $state('');
	let error = $state('');
	let busy = $state(false);

	async function submit(event: SubmitEvent): Promise<void> {
		event.preventDefault();
		busy = true;
		error = '';
		try {
			await api.login(password);
			password = '';
			onlogin();
		} catch (err) {
			if (err instanceof ApiError && err.status === 401) error = 'Mot de passe incorrect.';
			else if (err instanceof ApiError && err.status === 429) error = 'Trop d’essais. Réessaie dans un quart d’heure.';
			else error = 'Serveur injoignable. Vérifie ta connexion.';
		} finally {
			busy = false;
		}
	}
</script>

<form class="login" onsubmit={submit}>
	<h1>P.IGE</h1>
	<label for="password">Mot de passe</label>
	<input id="password" type="password" autocomplete="current-password" bind:value={password} required />
	{#if error}<p class="error" role="alert">{error}</p>{/if}
	<button class="btn primary" disabled={busy || !password}>Se connecter</button>
</form>

<style>
	.login {
		max-width: 340px;
		margin: 15vh auto 0;
		padding: 24px;
		display: flex;
		flex-direction: column;
		gap: 10px;
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 12px;
	}
	h1 {
		font-size: 1.75rem;
		margin-bottom: 8px;
	}
	label {
		font-size: 0.875rem;
		font-weight: 700;
		color: var(--muted);
	}
	input {
		min-height: 44px;
		padding: 0 12px;
		font: inherit;
		color: var(--ink);
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 8px;
	}
	.error {
		margin: 0;
		color: var(--accent);
	}
	button {
		min-height: 44px;
	}
</style>
