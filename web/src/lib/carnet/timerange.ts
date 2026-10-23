// A time range typed the way one writes it: « 9h30-11h », « 9:30 – 11:00 », « 14h », « 9h-midi ».

export interface Range {
	start: string | null; // "HH:MM"
	end: string | null;
}

function clock(text: string): string | null | undefined {
	const t = text.trim().toLowerCase();
	if (!t) return null;
	if (t === 'midi') return '12:00';
	if (t === 'minuit') return '00:00';
	const m = t.match(/^(\d{1,2})(?:\s*(?:h|:|\.)\s*(\d{2})?)?$/);
	if (!m) return undefined;
	const h = Number(m[1]);
	const min = m[2] ? Number(m[2]) : 0;
	if (h > 23 || min > 59) return undefined;
	return `${String(h).padStart(2, '0')}:${String(min).padStart(2, '0')}`;
}

/** The range typed, or undefined when it cannot be read. An empty text clears it. */
export function parseRange(text: string): Range | undefined {
	const parts = text.split(/\s*(?:-|–|—|à|>)\s*/);
	if (parts.length > 2) return undefined;
	const start = clock(parts[0]);
	const end = parts.length === 2 ? clock(parts[1]) : null;
	if (start === undefined || end === undefined) return undefined;
	if (!start && end) return undefined; // an end needs a start
	return { start, end };
}

/** Minutes from start to end; an end before the start is the next day. */
export function rangeMinutes(start: string | null, end: string | null): number | null {
	if (!start || !end) return null;
	const [a, b] = [start, end].map((x) => Number(x.slice(0, 2)) * 60 + Number(x.slice(3, 5)));
	return b > a ? b - a : b + 1440 - a;
}

export function formatRange(start: string | null, end: string | null): string {
	if (!start) return '';
	return end ? `${start}–${end}` : start;
}

export function formatMinutes(minutes: number): string {
	if (minutes < 60) return `${minutes} min`;
	const h = Math.floor(minutes / 60);
	const m = minutes % 60;
	return m ? `${h} h ${String(m).padStart(2, '0')}` : `${h} h`;
}

/** For the eye: « 9:30–11:00 » (no leading zero). */
export function showRange(start: string | null, end: string | null): string {
	const bare = (t: string) => t.replace(/^0(\d)/, '$1');
	if (!start) return '';
	return end ? `${bare(start)}–${bare(end)}` : bare(start);
}
