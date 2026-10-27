import { describe, expect, it } from 'vitest';
import { boxes, sameTitle } from './boxes.js';

describe('boxes', () => {
	it('lists the checkboxes, ticked or not, outside code', () => {
		const text = '# CR\n\n- [ ] CO2 harmonisé\n- [x] 3. Rappel\n  * [ ] sous-point\n- pas une case\n```\n- [ ] dans le code\n```\n- [ ]   \n';
		expect(boxes(text)).toEqual([
			{ title: 'CO2 harmonisé', done: false, line: 3 },
			{ title: '3. Rappel', done: true, line: 4 },
			{ title: 'sous-point', done: false, line: 5 }
		]);
	});
	it('matches a box and its task whatever the spaces and case', () => {
		expect(sameTitle('Taille  de police', 'taille de Police')).toBe(true);
		expect(sameTitle('Taille de police', 'Taille de polices')).toBe(false);
	});
});
