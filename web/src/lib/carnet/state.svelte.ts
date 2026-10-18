// Shared data of the new interface: the tree (spaces, projects, pinned tags) and known people.

import { v2, type Person, type Project, type Space, type Tree } from '../api2.js';

export const carnet = $state<{ tree: Tree | null; people: Person[]; error: string }>({
	tree: null,
	people: [],
	error: ''
});

export async function reload(): Promise<void> {
	const [tree, people] = await Promise.all([v2.tree(), v2.people()]);
	carnet.tree = tree;
	carnet.people = people;
	carnet.error = '';
}

export function allProjects(): Project[] {
	return carnet.tree?.spaces.flatMap((s) => s.projects) ?? [];
}

export function spaceOf(id: string | null | undefined): Space | undefined {
	return carnet.tree?.spaces.find((s) => s.id === id);
}

export function projectOf(id: string | null | undefined): Project | undefined {
	return allProjects().find((p) => p.id === id);
}

/** Where unsorted paragraphs go: the « À trier » space if there is one, else the first space. */
export function defaultSpace(): Space | undefined {
	const spaces = carnet.tree?.spaces ?? [];
	return spaces.find((s) => s.name.toLocaleLowerCase('fr') === 'à trier') ?? spaces[0];
}

export function todayIso(): string {
	const now = new Date();
	const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
	return local.toISOString().slice(0, 10);
}

export function shiftDay(day: string, delta: number): string {
	const d = new Date(`${day}T12:00:00`);
	d.setDate(d.getDate() + delta);
	const local = new Date(d.getTime() - d.getTimezoneOffset() * 60_000);
	return local.toISOString().slice(0, 10);
}

export function longDate(day: string): string {
	const text = new Date(`${day}T12:00:00`).toLocaleDateString('fr-FR', {
		weekday: 'long',
		day: 'numeric',
		month: 'long',
		year: day.slice(0, 4) === todayIso().slice(0, 4) ? undefined : 'numeric'
	});
	return text.charAt(0).toUpperCase() + text.slice(1);
}
