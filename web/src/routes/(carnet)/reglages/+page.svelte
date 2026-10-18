<script lang="ts">
	import { api } from '#lib/api.js';
	import CalendarSettings from '#lib/carnet/CalendarSettings.svelte';
	import { cache } from '#lib/carnet/capture.js';
	import { addPasskey, passkeysSupported, security, suggestedName, type Devices } from '#lib/carnet/passkeys.js';
	import { failure } from '#lib/carnet/state.svelte.js';

	let devices = $state<Devices | null>(null);
	let message = $state('');
	let info = $state('');
	let busy = $state(false);
	let newName = $state(passkeysSupported() ? suggestedName() : '');
	let renaming = $state<string | null>(null);
	let renameDraft = $state('');

	async function load() {
		try {
			devices = await security.devices();
		} catch (err) {
			message = failure(err, 'Réglages non chargés : ');
		}
	}

	$effect(() => {
		void load();
	});

	async function attempt(what: string, action: () => Promise<unknown>, done?: string) {
		message = '';
		info = '';
		busy = true;
		try {
			await action();
			if (done) info = done;
			await load();
		} catch (err) {
			if (err instanceof DOMException && (err.name === 'NotAllowedError' || err.name === 'AbortError')) {
				message = 'Opération annulée.';
			} else if (err instanceof DOMException && err.name === 'InvalidStateError') {
				message = 'Cet appareil a déjà une clé d’accès pour P.IGE.';
			} else {
				message = failure(err, `${what} : `);
			}
		} finally {
			busy = false;
		}
	}

	function when(seconds: number | null): string {
		if (!seconds) return 'jamais';
		const d = new Date(seconds * 1000);
		const days = Math.floor((Date.now() - d.getTime()) / 86_400_000);
		const time = d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
		if (days < 1 && d.getDate() === new Date().getDate()) return `aujourd’hui à ${time}`;
		return 'le ' + d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: days > 300 ? 'numeric' : undefined }) + ` à ${time}`;
	}

	function add(event: SubmitEvent) {
		event.preventDefault();
		void attempt('Clé d’accès non ajoutée', () => addPasskey(newName.trim() || suggestedName()), 'Clé d’accès ajoutée : la prochaine fois, connecte-toi sans mot de passe.');
	}

	function saveName(id: string) {
		const name = renameDraft.trim();
		renaming = null;
		if (name) void attempt('Nom non modifié', () => security.renamePasskey(id, name));
	}

	function remove(id: string, name: string) {
		if (!confirm(`Supprimer la clé d’accès « ${name} » ? Les appareils connectés avec elle seront déconnectés.`)) return;
		void attempt('Clé non supprimée', () => security.removePasskey(id), 'Clé d’accès supprimée.');
	}

	function endSession(id: string, label: string) {
		if (!confirm(`Déconnecter « ${label} » ?`)) return;
		void attempt('Appareil non déconnecté', () => security.endSession(id), 'Appareil déconnecté.');
	}

	function endOthers() {
		if (!confirm('Déconnecter tous les autres appareils ? Il faudra se reconnecter sur chacun.')) return;
		void attempt('Déconnexion impossible', async () => {
			const r = await security.endOthers();
			info = `${r.ended} appareil${r.ended > 1 ? 's' : ''} déconnecté${r.ended > 1 ? 's' : ''}.`;
		});
	}

	async function logout() {
		if (!confirm('Se déconnecter de cet appareil ?')) return;
		try {
			await api.logout();
			await cache.forget().catch(() => {});
			location.href = '/journal';
		} catch (err) {
			message = failure(err, 'Déconnexion impossible : ');
		}
	}
</script>

<svelte:head><title>Réglages · P.IGE</title></svelte:head>

<div class="wrap">
	<h1>Réglages</h1>
	{#if message}<p class="message" role="alert">{message}</p>{/if}
	{#if info}<p class="info" role="status">{info}</p>{/if}

	{#if !devices}
		<p class="muted">Chargement…</p>
	{:else}
		<section aria-labelledby="pk-title">
			<h2 id="pk-title">Clés d’accès</h2>
			<p class="hint">
				Une clé d’accès remplace le mot de passe : tu te connectes avec l’empreinte, le visage ou le code de l’appareil.
				Elle reste sur l’appareil (ou dans ton trousseau iCloud, Google…) et ne peut pas être volée par une fausse page.
			</p>
			{#if !devices.passkeys_configured}
				<p class="warn">
					Pas encore activées sur ce serveur : il faut indiquer son adresse dans <code>PIGE_PUBLIC_ORIGIN</code> (voir
					deploy/README.md).
				</p>
			{:else}
				<ul class="list">
					{#each devices.passkeys as pk (pk.id)}
						<li>
							<span class="main">
								{#if renaming === pk.id}
									<input bind:value={renameDraft} aria-label="Nom de la clé" onblur={() => saveName(pk.id)}
										onkeydown={(e) => {
											if (e.key === 'Enter') (e.currentTarget as HTMLInputElement).blur();
											if (e.key === 'Escape') renaming = null;
										}} />
								{:else}
									<b>{pk.name}</b>
								{/if}
								<small>
									ajoutée {when(pk.created_at)} · {pk.last_used ? `utilisée ${when(pk.last_used)}` : 'pas encore utilisée'}{pk.synced ? ' · synchronisée' : ''}
								</small>
							</span>
							<span class="actions">
								<button class="btn" onclick={() => { renaming = pk.id; renameDraft = pk.name; }}>Renommer</button>
								<button class="btn danger" onclick={() => remove(pk.id, pk.name)} disabled={busy}>Supprimer</button>
							</span>
						</li>
					{:else}
						<li class="muted">Aucune clé d’accès pour l’instant.</li>
					{/each}
				</ul>
				{#if passkeysSupported()}
					<form class="add" onsubmit={add}>
						<input bind:value={newName} aria-label="Nom de la nouvelle clé" placeholder="Nom de l’appareil" />
						<button class="btn primary" disabled={busy}>Ajouter une clé d’accès sur cet appareil</button>
					</form>
				{:else}
					<p class="muted">Ce navigateur ne gère pas les clés d’accès.</p>
				{/if}
			{/if}
		</section>

		<CalendarSettings />

		<section aria-labelledby="dev-title">
			<h2 id="dev-title">Appareils connectés</h2>
			<p class="hint">Où P.IGE est ouvert. Un téléphone perdu se déconnecte d’ici.</p>
			<ul class="list">
				{#each devices.sessions as s (s.id)}
					<li>
						<span class="main">
							<b>{s.label}{#if s.current} <span class="here">cet appareil</span>{/if}</b>
							<small>
								connecté {s.method === 'passkey' ? 'par clé d’accès' : 'par mot de passe'} {when(s.created_at)} · vu {when(s.last_seen)}
							</small>
						</span>
						<span class="actions">
							{#if s.current}
								<button class="btn" onclick={logout}>Se déconnecter</button>
							{:else}
								<button class="btn danger" onclick={() => endSession(s.id, s.label)} disabled={busy}>Déconnecter</button>
							{/if}
						</span>
					</li>
				{/each}
			</ul>
			{#if devices.sessions.length > 1}
				<button class="btn" onclick={endOthers} disabled={busy}>Déconnecter tous les autres appareils</button>
			{/if}
		</section>
	{/if}
</div>

<style>
	.wrap {
		padding: 22px 32px 48px;
		display: flex;
		flex-direction: column;
		gap: 16px;
		max-width: 820px;
	}
	h1 {
		font-size: 1.875rem;
		margin: 0;
	}
	h2 {
		font-size: 1.25rem;
		margin: 0;
		padding-bottom: 4px;
		border-bottom: var(--rule);
	}
	section {
		display: flex;
		flex-direction: column;
		gap: 10px;
	}
	section > .btn {
		align-self: flex-start;
	}
	.hint,
	.muted,
	small {
		font-size: 0.875rem;
		color: var(--muted);
	}
	.hint {
		margin: 0;
		max-width: 64ch;
	}
	.warn,
	.message {
		margin: 0;
		padding: 8px 12px;
		color: var(--warn);
		background: var(--warn-soft);
		border-radius: 8px;
	}
	.info {
		margin: 0;
		padding: 8px 12px;
		background: var(--soft);
		border-radius: 8px;
	}
	.list {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.list li {
		display: flex;
		flex-wrap: wrap;
		gap: 8px 16px;
		align-items: center;
		justify-content: space-between;
		padding: 10px 0;
		border-bottom: 1px solid var(--line);
	}
	.main {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}
	.here {
		margin-left: 6px;
		padding: 1px 6px;
		font-size: 0.75rem;
		color: var(--accent);
		border: 1px solid var(--accent);
		border-radius: 8px;
	}
	.actions {
		display: flex;
		gap: 6px;
	}
	.danger {
		color: var(--warn);
	}
	input {
		font: inherit;
		color: var(--ink);
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 6px;
		padding: 6px 10px;
		min-width: 0;
	}
	.add {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}
	.add input {
		flex: 1 1 200px;
	}
	@media (max-width: 600px) {
		.wrap {
			padding: 16px;
		}
	}
</style>
