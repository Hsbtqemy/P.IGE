import { describe, expect, it } from 'vitest';
import { fileName, mailLink, plainText, TEMPLATES } from './export.js';
import { outline } from './livePreview.js';

describe('outline', () => {
	it('lists headings with their line, outside code blocks', () => {
		const text = '# Titre\n\nTexte\n\n## Partie *une*\n```\n# pas un titre\n```\n### Détail\n#### trop profond';
		expect(outline(text)).toEqual([
			{ level: 1, text: 'Titre', line: 1 },
			{ level: 2, text: 'Partie une', line: 5 },
			{ level: 3, text: 'Détail', line: 9 }
		]);
	});
});

describe('exports', () => {
	it('makes safe file names', () => {
		expect(fileName('Compte rendu : réunion 12/03', 'md')).toBe('Compte rendu - reunion 12 - 03.md');
		expect(fileName('   ', 'doc')).toBe('texte.doc');
	});

	it('turns Markdown into readable plain text for a mail', () => {
		expect(plainText('## Décisions\n\n**Fait** et *noté*, voir [le site](https://ex.org) et `code`'))
			.toBe('Décisions\n\nFait et noté, voir le site (https://ex.org) et code');
	});

	it('flags mails too long for a mailto link', () => {
		expect(mailLink('CR', 'court').tooLong).toBe(false);
		expect(mailLink('CR', 'x'.repeat(3000)).tooLong).toBe(true);
	});

	it('fills templates with the title', () => {
		const cr = TEMPLATES.find((t) => t.id === 'cr')!;
		expect(cr.body('Réunion PPrim', '18 octobre 2026')).toContain('# Réunion PPrim');
		expect(cr.body('Réunion PPrim', '18 octobre 2026')).toContain('**Date :** 18 octobre 2026');
	});
});
