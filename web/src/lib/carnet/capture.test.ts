import { describe, expect, it } from 'vitest';
import type { Tree } from '../api2.js';
import { newId, prepare } from './capture.js';

const tree = {
	spaces: [
		{ id: 's1', name: 'FoReLLIS', position: 1, archived: false, projects: [{ id: 'p1', space_id: 's1', parent_id: null, name: 'DICODIACHRO', description: null, team: 'A', state: 'active', position: 1 }] },
		{ id: 's2', name: 'À trier', position: 2, archived: false, projects: [] }
	],
	pinned_tags: []
} as Tree;
const people = [{ display_name: 'Guilbard Anne-Cécile' }];

describe('prepare', () => {
	it('files a note like a journal paragraph, with ids for the entry and each task', () => {
		const c = prepare('Point DICODIACHRO avec @Guilbard #urgent\n[ ] Envoyer le devis', tree, people, { fallbackSpace: 's2' });
		expect(c.target).toEqual({ project_id: 'p1' });
		expect(c.people).toEqual(['Guilbard Anne-Cécile']);
		expect(c.tags).toEqual(['urgent']);
		expect(c.tasks.map((t) => t.title)).toEqual(['Envoyer le devis']);
		expect(c.id).toMatch(/^[0-9a-f]{32}$/);
		expect(c.tasks[0].id).toMatch(/^[0-9a-f]{32}$/);
		expect(c.tasks[0].id).not.toBe(c.id);
		expect(c.source).toBe('capture');
	});

	it('goes to the fallback space when no project is named, or where it is told', () => {
		expect(prepare('Idée en vrac', tree, people, { fallbackSpace: 's2' }).target).toEqual({ space_id: 's2' });
		expect(prepare('DICODIACHRO', tree, people, { place: { space_id: 's1' } }).target).toEqual({ space_id: 's1' });
	});

	it('works with nothing cached yet', () => {
		expect(prepare('Hors ligne', null, []).target).toEqual({ space_id: null });
	});

	it('makes distinct ids', () => {
		expect(new Set(Array.from({ length: 50 }, newId)).size).toBe(50);
	});
});
