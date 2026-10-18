<script lang="ts">
	import { v2, type CalendarInfo, type SyncResult } from '../api2.js';
	import { carnet, failure, placeName } from './state.svelte.js';

	let calendars = $state<CalendarInfo[] | null>(null);
	let message = $state('');
	let info = $state('');
	let busy = $state(false);
	let adding = $state(false);
	let editing = $state<string | null>(null);
	const empty = () => ({ name: '', url: '', username: '', password: '', color: '#3b5168', project: '' });
	let form = $state(empty());

	const COLORS = ['#3b5168', '#7a2e3a', '#3d7a4f', '#8a5300', '#5b4b8a', '#2f6f7a'];

	async function load() {
		try {
			calendars = await v2.calendars();
		} catch (err) {
			message = failure(err, 'Calendriers non chargés : ');
		}
	}

	$effect(() => {
		void load();
	});

	function report(sync: SyncResult | null, done: string) {
		if (!sync) info = done;
		else if (sync.ok) info = `${done} ${sync.added + sync.updated} événement${sync.added + sync.updated > 1 ? 's' : ''} lus.`;
		else message = `${done} Mais la lecture a échoué : ${sync.error}`;
	}

	async function run(what: string, action: () => Promise<void>) {
		message = '';
		info = '';
		busy = true;
		try {
			await action();
		} catch (err) {
			message = failure(err, `${what} : `);
		} finally {
			busy = false;
			await load();
		}
	}

	function add(event: SubmitEvent) {
		event.preventDefault();
		void run('Calendrier non ajouté', async () => {
			const r = await v2.addCalendar({
				name: form.name.trim(),
				url: form.url.trim(),
				username: form.username.trim() || null,
				password: form.password || null,
				color: form.color,
				project_id: form.project || null
			});
			form = empty();
			adding = false;
			report(r.sync, 'Calendrier ajouté.');
		});
	}

	function startEdit(c: CalendarInfo) {
		editing = c.id;
		form = { name: c.name, url: '', username: '', password: '', color: c.color, project: c.project_id ?? '' };
	}

	function save(c: CalendarInfo, event: SubmitEvent) {
		event.preventDefault();
		void run('Calendrier non modifié', async () => {
			const patch: Parameters<typeof v2.updateCalendar>[1] = {
				name: form.name.trim(),
				color: form.color,
				project_id: form.project || null
			};
			if (form.url.trim()) patch.url = form.url.trim();
			if (form.username.trim()) {
				patch.username = form.username.trim();
				if (form.password) patch.password = form.password;
			}
			const r = await v2.updateCalendar(c.id, patch);
			editing = null;
			form = empty();
			report(r.sync, 'Calendrier modifié.');
		});
	}

	function removeCredentials(c: CalendarInfo) {
		void run('Identifiants non retirés', async () => {
			const r = await v2.updateCalendar(c.id, { username: '' });
			report(r.sync, 'Identifiants retirés.');
		});
	}

	function toggle(c: CalendarInfo) {
		void run('Calendrier non modifié', async () => {
			const r = await v2.updateCalendar(c.id, { active: !c.active });
			report(r.sync, c.active ? 'Calendrier mis en pause.' : 'Calendrier repris.');
		});
	}

	function sync(c: CalendarInfo) {
		void run('Lecture impossible', async () => {
			report(await v2.syncCalendar(c.id), 'Calendrier relu.');
		});
	}

	function remove(c: CalendarInfo) {
		if (!confirm(`Ne plus suivre « ${c.name} » ? Ses événements disparaissent ; les notes et le temps déjà pris restent.`)) return;
		void run('Calendrier non supprimé', async () => {
			await v2.deleteCalendar(c.id);
			info = 'Calendrier retiré.';
		});
	}

	function when(iso: string | null): string {
		if (!iso) return 'jamais lu';
		return 'lu le ' + new Date(iso).toLocaleString('fr-FR', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
	}
</script>

{#snippet fields(edit: boolean)}
	<label>Nom <input bind:value={form.name} required maxlength="120" placeholder="Agenda université" /></label>
	<label class="wide">
		Adresse ICS {#if edit}<small>(laisser vide pour garder l’actuelle)</small>{/if}
		<input bind:value={form.url} required={!edit} type="url" inputmode="url" placeholder="https://… ou webcal://…" autocomplete="off" />
	</label>
	<label>
		Identifiant <small>(si le calendrier en demande un)</small>
		<input bind:value={form.username} autocomplete="off" />
	</label>
	<label>
		Mot de passe
		<input bind:value={form.password} type="password" autocomplete="new-password" placeholder={edit ? 'inchangé' : ''} />
	</label>
	<label>
		Notes et temps rangés dans
		<select bind:value={form.project}>
			<option value="">À trier</option>
			{#each carnet.tree?.spaces ?? [] as s (s.id)}
				<optgroup label={s.name}>{#each s.projects as p (p.id)}<option value={p.id}>{p.name}</option>{/each}</optgroup>
			{/each}
		</select>
	</label>
	<fieldset>
		<legend>Couleur</legend>
		{#each COLORS as c (c)}
			<label class="swatch" style="--c: {c}"><input type="radio" bind:group={form.color} value={c} aria-label="Couleur {c}" /></label>
		{/each}
	</fieldset>
{/snippet}

<section aria-labelledby="cal-title">
	<h2 id="cal-title">Calendriers</h2>
	<p class="hint">
		Les réunions de ton agenda apparaissent dans l’Agenda, le journal et Ma journée, où tu peux les noter ou compter leur
		temps. P.IGE lit l’adresse ICS (« iCal », « webcal ») toutes les quinze minutes, sans jamais rien écrire dans
		l’agenda. L’adresse et le mot de passe sont gardés chiffrés sur le serveur et ne sont plus jamais affichés.
	</p>
	{#if message}<p class="warn" role="alert">{message}</p>{/if}
	{#if info}<p class="info" role="status">{info}</p>{/if}
	{#if !calendars}
		<p class="muted">Chargement…</p>
	{:else}
		<ul class="list">
			{#each calendars as c (c.id)}
				<li>
					{#if editing === c.id}
						<form class="form" onsubmit={(e) => save(c, e)}>
							{@render fields(true)}
							<div class="row">
								<button class="btn primary" disabled={busy}>Enregistrer</button>
								<button type="button" class="btn" onclick={() => ((editing = null), (form = empty()))}>Annuler</button>
								{#if c.has_password}<button type="button" class="btn" onclick={() => removeCredentials(c)}>Retirer l’identifiant</button>{/if}
							</div>
						</form>
					{:else}
						<span class="main">
							<b><span class="dot" style="background: {c.color}"></span>{c.name}{#if !c.active} <small>(en pause)</small>{/if}</b>
							<small>
								{c.host}{c.has_password ? ' · avec identifiant' : ''} · {when(c.last_sync)} · rangé dans {c.project_id ? placeName({ project_id: c.project_id, space_id: '' }) : 'À trier'}
							</small>
							{#if c.last_error}<small class="error">{c.last_error}</small>{/if}
						</span>
						<span class="actions">
							<button class="btn" onclick={() => sync(c)} disabled={busy || !c.active}>Relire</button>
							<button class="btn" onclick={() => startEdit(c)}>Modifier</button>
							<button class="btn" onclick={() => toggle(c)} disabled={busy}>{c.active ? 'Pause' : 'Reprendre'}</button>
							<button class="btn danger" onclick={() => remove(c)} disabled={busy}>Retirer</button>
						</span>
					{/if}
				</li>
			{:else}
				<li class="muted">Aucun calendrier suivi.</li>
			{/each}
		</ul>
		{#if adding}
			<form class="form add" onsubmit={add}>
				{@render fields(false)}
				<div class="row">
					<button class="btn primary" disabled={busy}>{busy ? 'Lecture…' : 'Ajouter et lire'}</button>
					<button type="button" class="btn" onclick={() => ((adding = false), (form = empty()))}>Annuler</button>
				</div>
			</form>
		{:else if !editing}
			<button class="btn" onclick={() => ((form = empty()), (adding = true))}>Suivre un calendrier</button>
		{/if}
	{/if}
</section>

<style>
	section {
		display: flex;
		flex-direction: column;
		gap: 10px;
	}
	section > .btn {
		align-self: flex-start;
	}
	h2 {
		font-size: 1.25rem;
		margin: 0;
		padding-bottom: 4px;
		border-bottom: var(--rule);
	}
	.hint,
	.muted,
	small {
		font-size: 0.875rem;
		color: var(--muted);
		font-weight: 400;
	}
	.hint {
		margin: 0;
		max-width: 64ch;
	}
	.warn,
	.error {
		color: var(--warn);
	}
	p.warn {
		margin: 0;
		padding: 8px 12px;
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
	.list > li {
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
	.dot {
		display: inline-block;
		width: 10px;
		height: 10px;
		margin-right: 6px;
		border-radius: 50%;
	}
	.actions,
	.row {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.danger {
		color: var(--warn);
	}
	.form {
		flex: 1 1 100%;
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 10px 14px;
		padding: 12px;
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 10px;
	}
	.form label {
		display: flex;
		flex-direction: column;
		gap: 4px;
		font-size: 0.8125rem;
		font-weight: 700;
		color: var(--muted);
	}
	.form .wide,
	.form .row,
	fieldset {
		grid-column: 1 / -1;
	}
	input,
	select {
		font: inherit;
		font-weight: 400;
		font-size: 0.9375rem;
		color: var(--ink);
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 6px;
		padding: 6px 8px;
		min-width: 0;
	}
	fieldset {
		display: flex;
		gap: 8px;
		align-items: center;
		margin: 0;
		padding: 0;
		border: 0;
		font-size: 0.8125rem;
		font-weight: 700;
		color: var(--muted);
	}
	legend {
		float: left;
		margin-right: 6px;
	}
	.swatch {
		position: relative;
		width: 24px;
		height: 24px;
		border-radius: 50%;
		background: var(--c);
		cursor: pointer;
	}
	.swatch input {
		position: absolute;
		inset: 0;
		margin: 0;
		opacity: 0;
		cursor: pointer;
	}
	.swatch:has(input:checked) {
		outline: 2px solid var(--ink);
		outline-offset: 2px;
	}
	.swatch:has(input:focus-visible) {
		outline: 2px solid var(--accent);
		outline-offset: 2px;
	}
	@media (max-width: 600px) {
		.form {
			grid-template-columns: 1fr;
		}
	}
</style>
