<script lang="ts">
	import { onMount } from 'svelte';
	import { api, ApiError } from '../api.js';
	import { passkeysSupported, security, signInWithPasskey } from './passkeys.js';

	let { onlogin }: { onlogin: () => void } = $props();
	let password = $state('');
	let error = $state('');
	let busy = $state(false);
	let withPasskey = $state(false);

	onMount(async () => {
		if (!passkeysSupported()) return;
		try {
			withPasskey = (await security.status()).registered;
		} catch {
			/* offline or old server: password only */
		}
	});

	async function passkey(): Promise<void> {
		busy = true;
		error = '';
		try {
			await signInWithPasskey();
			onlogin();
		} catch (err) {
			if (err instanceof DOMException && (err.name === 'NotAllowedError' || err.name === 'AbortError')) {
				error = 'Connexion annulée, ou aucune clé d’accès de P.IGE sur cet appareil.';
			} else if (err instanceof ApiError && err.status === 429) error = 'Trop d’essais. Réessaie dans un quart d’heure.';
			else if (err instanceof ApiError && err.status === 0) error = 'Serveur injoignable. Vérifie ta connexion.';
			else error = 'Clé d’accès refusée. Utilise le mot de passe.';
		} finally {
			busy = false;
		}
	}

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
	{#if withPasskey}
		<button type="button" class="btn primary" disabled={busy} onclick={passkey}>Se connecter avec une clé d’accès</button>
		<p class="or">ou avec le mot de passe</p>
	{/if}
	<label for="password">Mot de passe</label>
	<input id="password" type="password" autocomplete="current-password" bind:value={password} required />
	{#if error}<p class="error" role="alert">{error}</p>{/if}
	<button class="btn" class:primary={!withPasskey} disabled={busy || !password}>Se connecter</button>
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
	.or {
		margin: 4px 0 0;
		font-size: 0.8125rem;
		color: var(--muted);
		text-align: center;
	}
	.error {
		margin: 0;
		color: var(--accent);
	}
	button {
		min-height: 44px;
	}
</style>
