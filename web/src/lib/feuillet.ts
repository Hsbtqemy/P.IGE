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

const MENTION = /@([\p{L}][\p{L}\p{M}.'’-]*(?:\s+[\p{Lu}][\p{L}\p{M}.'’-]*)?)/gu;
const TAG = /#([\p{L}\p{N}][\p{L}\p{N}\p{M}·._-]*[\p{L}\p{N}\p{M}])|#([\p{L}\p{N}])/gu;
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

export function resolvePerson(mention: string, people: KnownPerson[]): string {
	const matches = people.filter((p) => mentionMatches(mention, p.display_name));
	return matches.length === 1 ? matches[0].display_name : mention.trim();
}

function findProject(text: string, projects: KnownProject[]): KnownProject | null {
	const haystack = ` ${fold(text)} `;
	let best: { project: KnownProject; at: number; length: number } | null = null;
	for (const project of projects) {
		const needle = fold(project.name);
		if (needle.length < 3) continue;
		const at = haystack.indexOf(` ${needle} `);
		if (at < 0) continue;
		if (!best || needle.length > best.length || (needle.length === best.length && at < best.at)) {
			best = { project, at, length: needle.length };
		}
	}
	return best?.project ?? null;
}

function stripMarkers(line: string): string {
	return line.replace(DECISION, '').replace(/[@#]/g, '').replace(/\s+/g, ' ').trim();
}

export function read(text: string, projects: KnownProject[], people: KnownPerson[]): Reading {
	const lines = text.split('\n');
	const tasks = lines.map((l) => l.match(TASK_LINE)?.[1]).filter((t): t is string => !!t);
	const prose = lines.filter((l) => !TASK_LINE.test(l)).join('\n');

	const found: string[] = [];
	for (const m of text.matchAll(MENTION)) {
		const name = resolvePerson(m[1].replace(/[.'’-]+$/, ''), people);
		if (!found.some((f) => fold(f) === fold(name))) found.push(name);
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
