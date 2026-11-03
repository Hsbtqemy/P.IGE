import { describe, expect, it } from 'vitest';
import { fit, imageName, markdownImage } from './images.js';

describe('images', () => {
	it('shrinks only what is too big', () => {
		expect(fit(4000, 3000)).toBe(0.5);
		expect(fit(1200, 3000)).toBeCloseTo(2000 / 3000);
		expect(fit(1600, 900)).toBe(1);
	});
	it('names pasted images by the moment', () => {
		const pasted = new File([''], 'image.png', { type: 'image/png' });
		expect(imageName(pasted, new Date(2026, 10, 3, 18, 5))).toBe('capture 2026-11-03 18h05.png');
		expect(imageName(new File([''], 'tableau.jpg', { type: 'image/jpeg' }))).toBe('tableau.jpg');
	});
	it('writes the Markdown of an image', () => {
		expect(markdownImage({ id: 'a', entry_id: null, name: 'tableau [1].jpg', mime: 'image/jpeg', size: 1, width: 1, height: 1, url: '/api/v2/files/a' })).toBe(
			'![tableau 1](/api/v2/files/a)'
		);
	});
});
