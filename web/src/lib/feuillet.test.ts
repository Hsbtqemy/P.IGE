import { describe, expect, it } from 'vitest';
import { fold, read, resolvePerson, segments } from './feuillet';

const projects = [
	{ id: 'p1', name: 'DICODIACHRO', space_id: 's1' },
	{ id: 'p2', name: 'Photo non reproductible', space_id: 's1' },
	{ id: 'p3', name: 'POR FAVOR', space_id: 's2' },
	{ id: 'p4', name: 'Portail des revues', space_id: 's2' },
	{ id: 'p5', name: 'A', space_id: 's2' }
];
const people = [
	{ display_name: 'Thouverez Ludivine' },
	{ display_name: 'Guilbard Anne-Cécile' },
	{ display_name: 'Pacaud Jérôme' },
	{ display_name: 'Brunet Maréva' },
	{ display_name: 'Brunet Paul' }
];

describe('fold', () => {
	it('ignores accents, case and hyphens like the server', () => {
		expect(fold('PEYROL-KLEIBER Élodie')).toBe('peyrol kleiber elodie');
		expect(fold('Œuvre')).toBe('oeuvre');
	});
});

describe('read', () => {
	it('finds the project, people, tags, tasks and title', () => {
		const r = read(
			'Repris dicodiachro avec @A.-C. Guilbard et @J. Pacaud. #PPrim\n[ ] Récupérer le résultat final\n- [ ] Relire',
			projects,
			people
		);
		expect(r.project?.id).toBe('p1');
		expect(r.people).toEqual(['Guilbard Anne-Cécile', 'Pacaud Jérôme']);
		expect(r.tags).toEqual(['PPrim']);
		expect(r.tasks).toEqual(['Récupérer le résultat final', 'Relire']);
		expect(r.kind).toBe('note');
		expect(r.title).toBe('Repris dicodiachro avec A.-C. Guilbard et J. Pacaud. PPrim');
	});

	it('prefers the longest project name and ignores very short ones', () => {
		expect(read('Photo non reproductible : formats', projects, people).project?.id).toBe('p2');
		expect(read('Point A demain', projects, people).project).toBeNull();
		expect(read('POR FAVOR et Portail des revues', projects, people).project?.id).toBe('p4');
		expect(read('PORTAILS', projects, people).project).toBeNull(); // whole words only
	});

	it('spots decisions and keeps unknown or ambiguous people as written', () => {
		const r = read('Décision : TIFF pour l’archive, avec @Brunet et @Nouvelle Personne', projects, people);
		expect(r.kind).toBe('decision');
		expect(r.people).toEqual(['Brunet', 'Nouvelle Personne']);
		expect(r.title).toBe('TIFF pour l’archive, avec Brunet et Nouvelle Personne');
	});

	it('counts each person and tag once and shortens long titles', () => {
		const r = read(`@L. Thouverez @Ludivine #a #A ${'mot '.repeat(40)}`, projects, people);
		expect(r.people).toEqual(['Thouverez Ludivine']);
		expect(r.tags).toEqual(['a']);
		expect(r.title.length).toBeLessThanOrEqual(80);
		expect(r.title.endsWith('…')).toBe(true);
	});

	it('handles tags with middle dots', () => {
		expect(read('Café #doctorant·es !', projects, people).tags).toEqual(['doctorant·es']);
	});
});

describe('resolvePerson', () => {
	it('uses initials only when exactly one person matches', () => {
		expect(resolvePerson('M. Brunet', people)).toBe('Brunet Maréva');
		expect(resolvePerson('Brunet', people)).toBe('Brunet');
	});
});

describe('segments', () => {
	it('splits markers for display', () => {
		expect(segments('Café #doctorant·es avec @M. Brunet.')).toEqual([
			{ type: 'text', text: 'Café ' },
			{ type: 'tag', text: '#doctorant·es' },
			{ type: 'text', text: ' avec ' },
			{ type: 'person', text: '@M. Brunet.' },
		]);
		expect(segments('[ ] relancer')).toEqual([{ type: 'task', text: 'relancer' }]);
		expect(segments('Décision : TIFF')[0]).toEqual({ type: 'decision', text: 'Décision' });
	});
});
