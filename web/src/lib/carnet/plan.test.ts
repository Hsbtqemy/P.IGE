import { describe, expect, it } from 'vitest';
import type { Task } from '../api2.js';
import { byPlace, daysBetween, planDay } from './plan.js';

const task = (id: string, extra: Partial<Task> = {}): Task => ({
	id,
	space_id: 's',
	project_id: 'p',
	title: id,
	note: null,
	status: 'open',
	waiting_on: null,
	due_date: null,
	steps_done: 0,
	steps_total: 0,
	...extra
});

describe('planDay', () => {
	const day = '2026-10-20';
	it('puts each task in one place', () => {
		const plan = planDay(
			[
				task('due', { due_date: day }),
				task('doing', { status: 'in_progress' }),
				task('doing-late', { status: 'in_progress', due_date: '2026-09-01' }),
				task('late', { due_date: '2026-10-15' }),
				task('very-late', { due_date: '2026-03-01' }),
				task('tomorrow', { due_date: '2026-10-21' }),
				task('far', { due_date: '2026-12-01' }),
				task('waits', { status: 'waiting', waiting_on: 'x', due_date: '2026-10-01' }),
				task('nothing')
			],
			day
		);
		expect(plan.today.map((t) => t.id)).toEqual(['due', 'doing-late', 'doing']);
		expect(plan.recentLate.map((t) => t.id)).toEqual(['late']);
		expect(plan.oldLate.map((t) => t.id)).toEqual(['very-late']);
		expect(plan.ahead.map((t) => t.id)).toEqual(['tomorrow']);
		expect(plan.waiting.map((t) => t.id)).toEqual(['waits']);
	});

	it('groups by place and counts days', () => {
		const groups = byPlace([task('a'), task('b', { project_id: null, space_id: 'x' }), task('c')]);
		expect(groups.map((g) => [g.key, g.tasks.length])).toEqual([
			['p:p', 2],
			['s:x', 1]
		]);
		expect(daysBetween('2026-10-20', '2026-10-21')).toBe(1);
		expect(daysBetween('2026-10-20', '2026-03-29')).toBe(-205);
	});
});
