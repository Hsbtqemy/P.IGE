import { describe, expect, it } from 'vitest';
import { gaps } from './dayframe.js';

const t = (h: string) => `2026-10-23T${h}:00.000Z`;

describe('gaps', () => {
	it('finds the holes between counted time, merging overlaps', () => {
		const counted = [
			{ start: t('09:00'), end: t('10:00') },
			{ start: t('09:30'), end: t('11:00') },
			{ start: t('13:00'), end: t('17:00') }
		];
		expect(gaps(t('08:30'), t('18:00'), counted).map((g) => [g.start, g.minutes])).toEqual([
			[t('08:30'), 30],
			[t('11:00'), 120],
			[t('17:00'), 60]
		]);
	});
	it('leaves out short holes and what lies outside the day', () => {
		const counted = [
			{ start: t('07:00'), end: t('09:10') },
			{ start: t('09:20'), end: t('19:00') }
		];
		expect(gaps(t('09:00'), t('18:00'), counted)).toEqual([]);
		expect(gaps(t('09:00'), t('18:00'), [])).toEqual([{ start: t('09:00'), end: t('18:00'), minutes: 540 }]);
		expect(gaps(t('18:00'), t('09:00'), [])).toEqual([]);
	});
});
