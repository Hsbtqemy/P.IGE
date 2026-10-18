// Pure helpers of the quick search (Ctrl K): reading a date typed in words, matching names.

import { fold } from '../feuillet.js';

const MONTHS = [
	'janvier',
	'fevrier',
	'mars',
	'avril',
	'mai',
	'juin',
	'juillet',
	'aout',
	'septembre',
	'octobre',
	'novembre',
	'decembre'
];

function iso(y: number, m: number, d: number): string | null {
	const date = new Date(Date.UTC(y, m - 1, d));
	if (date.getUTCFullYear() !== y || date.getUTCMonth() !== m - 1 || date.getUTCDate() !== d) return null;
	return date.toISOString().slice(0, 10);
}

function shift(today: string, days: number): string {
	const date = new Date(`${today}T12:00:00Z`);
	date.setUTCDate(date.getUTCDate() + days);
	return date.toISOString().slice(0, 10);
}

/**
 * A day typed in words, relative to ``today`` (AAAA-MM-JJ):
 * « hier », « aujourd'hui », « demain », « 12/03 », « 12/03/2025 », « 12 mars », « 3 fév 2025 », « 2026-03-12 ».
 * Without a year, the date is in the current year.
 */
export function parseDay(text: string, today: string): string | null {
	const t = fold(text);
	if (!t) return null;
	if (t === 'aujourd hui' || t === 'auj') return today;
	if (t === 'hier') return shift(today, -1);
	if (t === 'avant hier') return shift(today, -2);
	if (t === 'demain') return shift(today, 1);
	const year = Number(today.slice(0, 4));
	let m = t.match(/^(\d{4}) (\d{1,2}) (\d{1,2})$/); // 2026-03-12 (fold turned - into spaces)
	if (m) return iso(Number(m[1]), Number(m[2]), Number(m[3]));
	m = text.trim().match(/^(\d{1,2})[/.](\d{1,2})(?:[/.](\d{2}|\d{4}))?$/);
	if (m) {
		const y = m[3] ? (m[3].length === 2 ? 2000 + Number(m[3]) : Number(m[3])) : year;
		return iso(y, Number(m[2]), Number(m[1]));
	}
	m = t.match(/^(\d{1,2}) ([a-z]{3,})(?: (\d{4}))?$/);
	if (m) {
		const word = m[2];
		const month = MONTHS.findIndex((name) => name.startsWith(word));
		if (month < 0) return null;
		return iso(m[3] ? Number(m[3]) : year, month + 1, Number(m[1]));
	}
	return null;
}

/** How well a name matches the typed words: 0 = no match, higher is better. */
export function score(name: string, query: string): number {
	const words = fold(query).split(' ').filter(Boolean);
	if (!words.length) return 0;
	const hay = fold(name);
	const tokens = hay.split(' ');
	let total = 0;
	for (const w of words) {
		if (tokens.some((t) => t === w)) total += 3;
		else if (tokens.some((t) => t.startsWith(w))) total += 2;
		else if (hay.includes(w)) total += 1;
		else return 0;
	}
	return total + (hay.startsWith(words[0]) ? 1 : 0);
}

/** « …les [métadonnées] du… » -> parts to show, the bracketed ones highlighted. */
export function highlight(snippet: string): { text: string; hit: boolean }[] {
	const parts: { text: string; hit: boolean }[] = [];
	const re = /\[([^\]]*)\]/g;
	let last = 0;
	for (const m of snippet.matchAll(re)) {
		const at = m.index ?? 0;
		if (at > last) parts.push({ text: snippet.slice(last, at), hit: false });
		parts.push({ text: m[1], hit: true });
		last = at + m[0].length;
	}
	if (last < snippet.length) parts.push({ text: snippet.slice(last), hit: false });
	return parts;
}
