<script lang="ts">
	import { tick } from 'svelte';
	import { goto } from '$app/navigation';
	import { v2, type SearchHit } from '../api2.js';
	import { highlight, parseDay, score } from './palette.js';
	import { allProjects, carnet, failure, longDate, placeName, spaceOf, todayIso } from './state.svelte.js';

	let { open = $bindable(false) }: { open?: boolean } = $props();

	interface Item {
		key: string;
		group: string;
		label: string;
		detail?: string;
		snippet?: string;
		run: () => void | Promise<void>;
	}

	let query = $state('');
	let hits = $state<SearchHit[]>([]);
	let searching = $state(false);
	let active = $state(0);
	let message = $state('');
	let input = $state<HTMLInputElement | null>(null);
	let previousFocus: HTMLElement | null = null;
	let timer: ReturnType<typeof setTimeout> | undefined;
	let asked = 0;

	$effect(() => {
		if (!open) return;
		previousFocus = document.activeElement as HTMLElement | null;
		query = '';
		hits = [];
		active = 0;
		message = '';
		void tick().then(() => input?.focus());
	});

	function close() {
		open = false;
		previousFocus?.focus?.();
	}

	function onInput() {
		active = 0;
		message = '';
		clearTimeout(timer);
		const text = query.trim();
		if (text.length < 2) {
			hits = [];
			searching = false;
			return;
		}
		searching = true;
		const ticket = ++asked;
		timer = setTimeout(async () => {
			try {
				const found = await v2.search(text, 15);
				if (ticket === asked) hits = found;
			} catch (err) {
				if (ticket === asked) message = failure(err, 'Recherche impossible : ');
			} finally {
				if (ticket === asked) searching = false;
			}
		}, 160);
	}

	/** The snippet only repeats the title: not worth a second line. */
	function same(snippet: string, title: string): boolean {
		return snippet.replace(/[[\]…]/g, '').trim() === title.trim();
	}

	function go(href: string) {
		open = false;
		void goto(href);
	}

	async function startTimer(projectId: string, name: string) {
		try {
			const timer = await v2.startTimer({ project_id: projectId });
			carnet.timers = [...carnet.timers, timer];
			go(`/journee/${todayIso()}`);
		} catch (err) {
			message = failure(err, `Minuteur sur ${name} non démarré : `);
		}
	}

	const PAGES: { label: string; href: () => string; words: string }[] = [
		{ label: 'Journal du jour', href: () => `/journal/${todayIso()}`, words: 'journal feuillet aujourd hui ecrire' },
		{ label: 'Ma journée', href: () => `/journee/${todayIso()}`, words: 'ma journee minuteur temps chrono bilan' },
		{ label: 'Personnes', href: () => '/personnes', words: 'personnes contacts annuaire gens' },
		{ label: 'Étiquettes', href: () => '/etiquettes', words: 'etiquettes tags' }
	];

	let items = $derived.by((): Item[] => {
		const text = query.trim();
		const out: Item[] = [];
		const day = parseDay(text, todayIso());
		if (day) out.push({ key: `day:${day}`, group: 'Aller à', label: `Journal du ${longDate(day).toLocaleLowerCase('fr')}`, run: () => go(`/journal/${day}`) });
		for (const p of PAGES) {
			if (!text || score(`${p.label} ${p.words}`, text)) {
				out.push({ key: `page:${p.label}`, group: 'Aller à', label: p.label, run: () => go(p.href()) });
			}
		}
		if (!text) return out;

		const projects = allProjects()
			.map((p) => ({ p, s: score(p.name, text) }))
			.filter((x) => x.s > 0)
			.sort((a, b) => b.s - a.s)
			.slice(0, 6);
		for (const { p } of projects) {
			out.push({ key: `project:${p.id}`, group: 'Projets', label: p.name, detail: spaceOf(p.space_id)?.name, run: () => go(`/projets/${p.id}`) });
		}
		if (projects.length) {
			const top = projects[0].p;
			out.push({
				key: `timer:${top.id}`,
				group: 'Projets',
				label: `▶ Démarrer un minuteur sur ${top.name}`,
				run: () => startTimer(top.id, top.name)
			});
		}
		const people = carnet.people
			.map((p) => ({ p, s: score(`${p.display_name} ${p.organisation ?? ''}`, text) }))
			.filter((x) => x.s > 0)
			.sort((a, b) => b.s - a.s)
			.slice(0, 6);
		for (const { p } of people) {
			out.push({ key: `person:${p.id}`, group: 'Personnes', label: p.display_name, detail: p.organisation ?? undefined, run: () => go(`/personnes/${p.id}`) });
		}
		for (const t of carnet.tree?.pinned_tags ?? []) {
			if (score(t.name, text.replace(/^#/, ''))) {
				out.push({ key: `tag:${t.id}`, group: 'Étiquettes', label: `#${t.name}`, run: () => go(`/etiquettes/${t.id}`) });
			}
		}
		for (const h of hits) {
			const where = placeName({ project_id: h.project_id, space_id: h.space_id });
			if (h.kind === 'task') {
				out.push({
					key: `task:${h.id}`,
					group: 'Tâches',
					label: h.title,
					detail: where + (h.status === 'done' ? ' · terminée' : ''),
					snippet: same(h.snippet, h.title) ? undefined : h.snippet,
					// Finished: Ma journée of the day it was ticked lists it with « Rouvrir ».
					run: () =>
						go(
							h.status === 'done' && h.done_at
								? `/journee/${localDay(h.done_at)}`
								: `${h.project_id ? `/projets/${h.project_id}` : `/espaces/${h.space_id}`}?tache=${h.id}`
						)
				});
			} else {
				out.push({
					key: `entry:${h.id}`,
					group: 'Journal',
					label: h.title || '(sans titre)',
					detail: `${h.entry_date ? longDate(h.entry_date) : ''} · ${where}`,
					snippet: same(h.snippet, h.title) ? undefined : h.snippet,
					run: () => go(`/journal/${h.entry_date ?? todayIso()}`)
				});
			}
		}
		return out;
	});

	function onKey(event: KeyboardEvent) {
		if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
			event.preventDefault();
			if (!items.length) return;
			active = (active + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
			void tick().then(() => document.getElementById(`pal-${active}`)?.scrollIntoView({ block: 'nearest' }));
		} else if (event.key === 'Enter') {
			event.preventDefault();
			void items[active]?.run();
		} else if (event.key === 'Escape') {
			event.preventDefault();
			close();
		} else if (event.key === 'Tab') {
			event.preventDefault(); // focus stays in the dialog
		}
	}

	function localDay(iso: string): string {
		const d = new Date(iso);
		return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
	}
</script>

{#if open}
	<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
	<div class="backdrop" onclick={close}></div>
	<div class="palette" role="dialog" aria-modal="true" aria-label="Recherche rapide">
		<input
			bind:this={input}
			bind:value={query}
			oninput={onInput}
			onkeydown={onKey}
			placeholder="Projet, personne, tâche, mot du journal, date (« hier », « 12 mars »)…"
			role="combobox"
			aria-expanded="true"
			aria-controls="pal-list"
			aria-activedescendant={items.length ? `pal-${active}` : undefined}
			aria-autocomplete="list"
		/>
		<ul id="pal-list" role="listbox" aria-label="Résultats">
			{#each items as item, i (item.key)}
				{#if i === 0 || items[i - 1].group !== item.group}
					<li class="group" role="presentation">{item.group}</li>
				{/if}
				<li
					id="pal-{i}"
					role="option"
					aria-selected={i === active}
					class:active={i === active}
					onmousemove={() => (active = i)}
					onclick={() => item.run()}
					onkeydown={() => {}}
				>
					<span class="label">{item.label}</span>
					{#if item.detail}<small>{item.detail}</small>{/if}
					{#if item.snippet}
						<span class="snippet">{#each highlight(item.snippet) as part, j (j)}{#if part.hit}<mark>{part.text}</mark>{:else}{part.text}{/if}{/each}</span>
					{/if}
				</li>
			{/each}
			{#if searching}<li class="note" role="presentation">Recherche…</li>{/if}
			{#if !searching && query.trim().length >= 2 && !items.length}<li class="note" role="presentation">Rien trouvé.</li>{/if}
			{#if message}<li class="note warn" role="presentation">{message}</li>{/if}
		</ul>
		<p class="keys" aria-hidden="true">↑ ↓ pour choisir · Entrée pour ouvrir · Échap pour fermer</p>
	</div>
{/if}

<style>
	.backdrop {
		position: fixed;
		inset: 0;
		z-index: 20;
		background: rgb(30 35 32 / 0.35);
	}
	.palette {
		position: fixed;
		z-index: 21;
		top: 12vh;
		left: 50%;
		width: min(640px, calc(100vw - 24px));
		transform: translateX(-50%);
		display: flex;
		flex-direction: column;
		max-height: 72vh;
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 12px;
		box-shadow: 0 18px 48px rgb(0 0 0 / 0.22);
		overflow: hidden;
	}
	input {
		padding: 14px 16px;
		font: inherit;
		font-size: 1.0625rem;
		color: var(--ink);
		background: transparent;
		border: 0;
		border-bottom: 1px solid var(--line);
		outline: none;
	}
	ul {
		list-style: none;
		margin: 0;
		padding: 6px;
		overflow-y: auto;
	}
	.group {
		padding: 10px 10px 4px;
		font-size: 0.75rem;
		font-weight: 700;
		color: var(--muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	[role='option'] {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 2px 10px;
		padding: 8px 10px;
		border-radius: 8px;
		cursor: pointer;
	}
	[role='option'].active {
		background: var(--soft);
	}
	.label {
		font-weight: 700;
		min-width: 0;
		overflow-wrap: anywhere;
	}
	small {
		font-size: 0.8125rem;
		color: var(--muted);
	}
	.snippet {
		flex-basis: 100%;
		font-size: 0.8125rem;
		color: var(--muted);
	}
	mark {
		color: var(--ink);
		background: var(--warn-soft);
		border-radius: 2px;
	}
	.note {
		padding: 10px;
		font-size: 0.875rem;
		color: var(--muted);
	}
	.warn {
		color: var(--warn);
	}
	.keys {
		margin: 0;
		padding: 8px 14px;
		font-size: 0.75rem;
		color: var(--muted);
		border-top: 1px solid var(--line);
	}
	@media (max-width: 600px) {
		.palette {
			top: 8px;
			max-height: calc(100dvh - 16px);
		}
		.keys {
			display: none;
		}
	}
</style>
