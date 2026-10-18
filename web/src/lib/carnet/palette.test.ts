import { describe, expect, it } from 'vitest';
import { highlight, parseDay, score } from './palette.js';

const TODAY = '2026-10-18';

describe('parseDay', () => {
	it('reads relative words', () => {
		expect(parseDay('hier', TODAY)).toBe('2026-10-17');
		expect(parseDay("Aujourd'hui", TODAY)).toBe(TODAY);
		expect(parseDay('demain', TODAY)).toBe('2026-10-19');
		expect(parseDay('avant-hier', TODAY)).toBe('2026-10-16');
	});

	it('reads numeric dates, day first', () => {
		expect(parseDay('12/03', TODAY)).toBe('2026-03-12');
		expect(parseDay('12/03/2025', TODAY)).toBe('2025-03-12');
		expect(parseDay('1.2.25', TODAY)).toBe('2025-02-01');
		expect(parseDay('2026-03-12', TODAY)).toBe('2026-03-12');
	});

	it('reads month names, with or without accents and abbreviated', () => {
		expect(parseDay('12 mars', TODAY)).toBe('2026-03-12');
		expect(parseDay('3 février 2025', TODAY)).toBe('2025-02-03');
		expect(parseDay('3 fev', TODAY)).toBe('2026-02-03');
		expect(parseDay('15 août', TODAY)).toBe('2026-08-15');
		expect(parseDay('1 juil', TODAY)).toBe('2026-07-01');
	});

	it('refuses what is not a real date', () => {
		expect(parseDay('31/02', TODAY)).toBeNull();
		expect(parseDay('12 marsupial', TODAY)).toBeNull();
		expect(parseDay('dicodiachro', TODAY)).toBeNull();
		expect(parseDay('12', TODAY)).toBeNull();
		expect(parseDay('', TODAY)).toBeNull();
	});
});

describe('score', () => {
	it('matches every word, accents and case ignored', () => {
		expect(score('Guilbard Anne-Cécile', 'anne cec')).toBeGreaterThan(0);
		expect(score('Guilbard Anne-Cécile', 'anne martin')).toBe(0);
	});

	it('prefers whole words, then prefixes, then inner matches', () => {
		expect(score('POR FAVOR', 'por')).toBeGreaterThan(score('PORTAIL DES REVUES', 'por'));
		expect(score('PORTAIL DES REVUES', 'por')).toBeGreaterThan(score('SUPPORT', 'por'));
	});
});

describe('highlight', () => {
	it('splits the server snippet on its brackets', () => {
		expect(highlight('…les [métadonnées] du [projet]')).toEqual([
			{ text: '…les ', hit: false },
			{ text: 'métadonnées', hit: true },
			{ text: ' du ', hit: false },
			{ text: 'projet', hit: true }
		]);
	});
});
