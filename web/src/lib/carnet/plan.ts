// The day's plan (Ma journée): what is due that day and what is in progress, then what is
// late, what comes next, what others owe. Pure functions, so they can be tested.
import type { Task } from '../api2.js';

/** Late for at most this many days: still in plain sight; older ones are folded. */
export const RECENT_LATE_DAYS = 7;
/** « Prochains jours »: due within this many days after the day. */
export const AHEAD_DAYS = 7;

export interface DayPlan {
	/** Due that day, or in progress (late ones included: you are on them). */
	today: Task[];
	/** Late by at most RECENT_LATE_DAYS, not in progress. */
	recentLate: Task[];
	/** Late for longer, not in progress (folded). */
	oldLate: Task[];
	/** Due in the next AHEAD_DAYS days. */
	ahead: Task[];
	/** Waiting on someone, not due that day. */
	waiting: Task[];
}

function addDays(day: string, delta: number): string {
	const d = new Date(`${day}T12:00:00Z`);
	d.setUTCDate(d.getUTCDate() + delta);
	return d.toISOString().slice(0, 10);
}

export function planDay(tasks: Task[], day: string): DayPlan {
	const plan: DayPlan = { today: [], recentLate: [], oldLate: [], ahead: [], waiting: [] };
	const recentFrom = addDays(day, -RECENT_LATE_DAYS);
	const aheadTo = addDays(day, AHEAD_DAYS);
	for (const t of tasks) {
		if (t.status === 'done') continue;
		const due = t.due_date ?? '';
		if (due === day || (t.status === 'in_progress' && (!due || due <= day))) plan.today.push(t);
		else if (due && due < day && t.status !== 'waiting') (due >= recentFrom ? plan.recentLate : plan.oldLate).push(t);
		else if (t.status === 'waiting') plan.waiting.push(t);
		else if (due && due > day && due <= aheadTo) plan.ahead.push(t);
	}
	const byDue = (a: Task, b: Task) => (a.due_date ?? '9999').localeCompare(b.due_date ?? '9999');
	plan.today.sort((a, b) => Number(b.due_date === day) - Number(a.due_date === day) || byDue(a, b));
	plan.recentLate.sort((a, b) => byDue(b, a)); // the most recently late first
	plan.oldLate.sort((a, b) => byDue(b, a));
	plan.ahead.sort(byDue);
	plan.waiting.sort((a, b) => (a.status_since ?? '').localeCompare(b.status_since ?? ''));
	return plan;
}

/** Tasks grouped by project (or space), in the order of their first task. */
export function byPlace(tasks: Task[]): { key: string; target: Task; tasks: Task[] }[] {
	const groups = new Map<string, { key: string; target: Task; tasks: Task[] }>();
	for (const t of tasks) {
		const key = t.project_id ? `p:${t.project_id}` : `s:${t.space_id}`;
		const group = groups.get(key) ?? { key, target: t, tasks: [] };
		group.tasks.push(t);
		groups.set(key, group);
	}
	return [...groups.values()];
}

/** Days between two AAAA-MM-JJ dates (b - a). */
export function daysBetween(a: string, b: string): number {
	return Math.round((Date.parse(`${b}T12:00:00Z`) - Date.parse(`${a}T12:00:00Z`)) / 86_400_000);
}
