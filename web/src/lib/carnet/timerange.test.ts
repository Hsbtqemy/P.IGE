import { describe, expect, it } from 'vitest';
import { formatMinutes, formatRange, parseRange, rangeMinutes, showRange } from './timerange.js';

describe('parseRange', () => {
	it('reads the usual ways of writing a range', () => {
		expect(parseRange('9h30-11h')).toEqual({ start: '09:30', end: '11:00' });
		expect(parseRange('9:30 – 11:00')).toEqual({ start: '09:30', end: '11:00' });
		expect(parseRange('14h à 15h45')).toEqual({ start: '14:00', end: '15:45' });
		expect(parseRange('9h-midi')).toEqual({ start: '09:00', end: '12:00' });
		expect(parseRange('8')).toEqual({ start: '08:00', end: null });
		expect(parseRange('10h15 -')).toEqual({ start: '10:15', end: null });
	});
	it('clears with an empty text and refuses the rest', () => {
		expect(parseRange('')).toEqual({ start: null, end: null });
		expect(parseRange('25h')).toBeUndefined();
		expect(parseRange('9h70')).toBeUndefined();
		expect(parseRange('demain')).toBeUndefined();
		expect(parseRange('- 11h')).toBeUndefined();
		expect(parseRange('9h-10h-11h')).toBeUndefined();
	});
});

describe('durations', () => {
	it('counts minutes, across midnight too', () => {
		expect(rangeMinutes('09:30', '11:00')).toBe(90);
		expect(rangeMinutes('23:00', '01:00')).toBe(120);
		expect(rangeMinutes('09:30', null)).toBeNull();
		expect(formatMinutes(90)).toBe('1 h 30');
		expect(formatMinutes(45)).toBe('45 min');
		expect(formatRange('09:30', '11:00')).toBe('09:30–11:00');
		expect(formatRange('09:30', null)).toBe('09:30');
		expect(showRange('09:30', '11:00')).toBe('9:30–11:00');
		expect(showRange('10:05', null)).toBe('10:05');
	});
});
