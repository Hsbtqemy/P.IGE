// The frame of a day: the holes between counted time, and the thresholds of a long day.

export const LONG_DAY = 10 * 3600; // seconds: a day this long is pointed out
export const LONG_WEEK = 45 * 3600;

export interface Gap {
	start: string; // ISO instants
	end: string;
	minutes: number;
}

/** Stretches of the day (start → end) not covered by any counted interval, the short ones left out. */
export function gaps(start: string, end: string, intervals: { start: string; end: string }[], minMinutes = 20): Gap[] {
	const lo = new Date(start).getTime();
	const hi = new Date(end).getTime();
	if (!(hi > lo)) return [];
	const spans = intervals
		.map((i) => [Math.max(lo, new Date(i.start).getTime()), Math.min(hi, new Date(i.end).getTime())] as const)
		.filter(([a, b]) => b > a)
		.sort((x, y) => x[0] - y[0]);
	const out: Gap[] = [];
	let cursor = lo;
	const push = (a: number, b: number) => {
		const minutes = Math.round((b - a) / 60_000);
		if (minutes >= minMinutes) out.push({ start: new Date(a).toISOString(), end: new Date(b).toISOString(), minutes });
	};
	for (const [a, b] of spans) {
		if (a > cursor) push(cursor, a);
		cursor = Math.max(cursor, b);
	}
	if (hi > cursor) push(cursor, hi);
	return out;
}

/** « 08:45 » in local time for an ISO instant. */
export function hhmm(iso: string): string {
	const d = new Date(iso);
	return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

/** A local « HH:MM » on a day as an ISO instant; ``after``: an earlier clock is the next day. */
export function atClock(day: string, clock: string, after?: string): string {
	let d = new Date(`${day}T${clock}:00`);
	if (after && d <= new Date(after)) d = new Date(d.getTime() + 86_400_000);
	return d.toISOString();
}
