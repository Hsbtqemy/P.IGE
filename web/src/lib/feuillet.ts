// Reading a journal paragraph: where it belongs and what it creates.
//
//   project names   recognised as written (accents, case and hyphens ignored)
//   @Name           a person (matched against known people, initials allowed: "@L. Thouverez")
//   #tag            a tag
//   [ ] text        a task, on its own line
//   Décision :      the paragraph is a decision

export interface KnownProject {
	id: string;
	name: string;
	space_id: string;
}

export interface KnownPerson {
	display_name: string;
}

export interface Reading {
	project: KnownProject | null;
	people: string[];
	/** Mentions matching several known people: not linked, shown to the user. */
	ambiguous: string[];
	tags: string[];
	tasks: string[];
	kind: 'note' | 'decision';
	title: string;
}

export type Segment =
	| { type: 'text'; text: string }
	| { type: 'person'; text: string }
	| { type: 'tag'; text: string }
	| { type: 'task'; text: string }
	| { type: 'decision'; text: string };

/** "PEYROL-KLEIBER Élodie" -> "peyrol kleiber elodie" (same rule as the server). */
/** fold() plus punctuation turned into spaces, for whole-word matching. */
function words(text: string): string {
	return fold(text).replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
}

export function fold(text: string): string {
	return text
		.replace(/œ/g, 'oe')
		.replace(/Œ/g, 'OE')
		.replace(/æ/g, 'ae')
		.replace(/Æ/g, 'AE')
		.normalize('NFKD')
		.replace(/\p{M}/gu, '')
		.toLowerCase()
		.replace(/[\s\-‐-―_.'’]+/g, ' ')
		.trim();
}

// "@Paul", "@J.-L. Duchet", "@Anne-Cécile Guilbard"; not "jean@example.com", never across lines.
const MENTION =
	/(?<![\p{L}\p{N}._%+-])@((?:\p{Lu}\.(?:-\p{Lu}\.)?|\p{L}[\p{L}\p{M}'’-]*)(?:[ \t]+\p{Lu}[\p{L}\p{M}'’-]*)?)/gu;
// "#PPrim", "#doctorant·es"; not "page#section" or "&#39;".
const TAG = /(?<![\p{L}\p{N}/&])#([\p{L}\p{N}][\p{L}\p{N}\p{M}·._-]*[\p{L}\p{N}\p{M}]|[\p{L}\p{N}])/gu;
const TASK_LINE = /^\s*(?:[-*]\s*)?\[\s?\]\s+(.+?)\s*$/;
const DECISION = /^\s*d[ée]cision\s*:\s*/i;

function tokens(text: string): string[] {
	return fold(text).split(' ').filter(Boolean);
}

/** A mention matches a person when each of its words is one of the person's words or its initial. */
function mentionMatches(mention: string, person: string): boolean {
	const wanted = tokens(mention);
	const have = tokens(person);
	if (!wanted.length) return false;
	return wanted.every((w) => have.some((h) => h === w || (w.length === 1 && h.startsWith(w))));
}

export function resolvePerson(mention: string, people: KnownPerson[]): { name: string; ambiguous: boolean } {
	const matches = people.filter((p) => mentionMatches(mention, p.display_name));
	if (matches.length === 1) return { name: matches[0].display_name, ambiguous: false };
	return { name: mention.trim(), ambiguous: matches.length > 1 };
}

function findProject(text: string, projects: KnownProject[]): KnownProject | null {
	const haystack = ` ${words(text)} `;
	let best: { project: KnownProject; at: number; length: number } | null = null;
	for (const project of projects) {
		const needle = words(project.name);
		if (needle.length < 3) continue;
		const at = haystack.indexOf(` ${needle} `);
		if (at < 0) continue;
		if (!best || needle.length > best.length || (needle.length === best.length && at < best.at)) {
			best = { project, at, length: needle.length };
		}
	}
	return best?.project ?? null;
}

/** Text without the markers' signs: "@Paul" -> "Paul", "#PPrim" -> "PPrim", URLs untouched. */
export function stripMarkers(line: string): string {
	return line
		.replace(DECISION, '')
		.replace(MENTION, (m) => m.slice(1))
		.replace(TAG, (m) => m.slice(1))
		.replace(/\s+/g, ' ')
		.trim();
}

export function read(text: string, projects: KnownProject[], people: KnownPerson[]): Reading {
	const lines = text.split('\n');
	const tasks = lines
		.map((l) => l.match(TASK_LINE)?.[1])
		.filter((t): t is string => !!t)
		.map(stripMarkers);
	const prose = lines.filter((l) => !TASK_LINE.test(l)).join('\n');

	const found: string[] = [];
	const ambiguous: string[] = [];
	for (const m of text.matchAll(MENTION)) {
		const { name, ambiguous: unclear } = resolvePerson(m[1].replace(/['’-]+$/, ''), people);
		const list = unclear ? ambiguous : found;
		if (!list.some((f) => fold(f) === fold(name))) list.push(name);
	}
	const tags: string[] = [];
	for (const m of text.matchAll(TAG)) {
		const tag = m[1] ?? m[2];
		if (!tags.some((t) => t.toLowerCase() === tag.toLowerCase())) tags.push(tag);
	}
	const firstLine = (prose.split('\n').find((l) => l.trim()) ?? tasks[0] ?? '').trim();
	let title = stripMarkers(firstLine);
	if (title.length > 80) title = title.slice(0, 79).replace(/\s+\S*$/, '') + '…';

	return {
		project: findProject(text, projects),
		people: found,
		ambiguous,
		tags,
		tasks,
		kind: DECISION.test(prose) || lines.some((l) => DECISION.test(l)) ? 'decision' : 'note',
		title
	};
}

/** Split a line of text into plain text and highlighted markers, for display. */
export function segments(line: string): Segment[] {
	const task = line.match(TASK_LINE);
	if (task) return [{ type: 'task', text: task[1] }];
	const out: Segment[] = [];
	let rest = line;
	const decision = rest.match(DECISION);
	if (decision) {
		out.push({ type: 'decision', text: 'Décision' });
		rest = rest.slice(decision[0].length);
	}
	const marker = new RegExp(`${MENTION.source}|${TAG.source}`, 'gu');
	let last = 0;
	for (const m of rest.matchAll(marker)) {
		const at = m.index ?? 0;
		if (at > last) out.push({ type: 'text', text: rest.slice(last, at) });
		out.push(m[0].startsWith('@') ? { type: 'person', text: m[0] } : { type: 'tag', text: m[0] });
		last = at + m[0].length;
	}
	if (last < rest.length) out.push({ type: 'text', text: rest.slice(last) });
	return out;
}
