// Client for the new model API (/api/v2). Same session and CSRF header as api.ts.

import { request } from './api.js';

export type TaskStatus = 'open' | 'in_progress' | 'waiting' | 'done';
export type EntryKind = 'note' | 'meeting' | 'decision' | 'activity';

export interface Space {
	id: string;
	name: string;
	position: number;
	archived: boolean;
}

export interface Project {
	id: string;
	space_id: string;
	parent_id: string | null;
	name: string;
	description: string | null;
	team: string | null;
	state: 'active' | 'dormant' | 'closed';
	position: number;
	open_tasks?: number;
}

export interface Tag {
	id: string;
	name: string;
	pinned: boolean;
	uses?: number;
}

export interface Person {
	id: string;
	display_name: string;
	email: string | null;
	organisation: string | null;
	role: string | null;
	last_exchange?: string | null;
}

export interface Entry {
	id: string;
	space_id: string;
	project_id: string | null;
	task_id: string | null;
	kind: EntryKind;
	title: string;
	body: string;
	entry_date: string;
	start_time: string | null;
	end_time: string | null;
	decision_applied: boolean | null;
	source: string;
	created_at: string;
	updated_at: string;
	version: number;
	revision: number;
	people: Person[];
	tags: Tag[];
}

export interface Task {
	id: string;
	space_id: string;
	project_id: string | null;
	title: string;
	note: string | null;
	status: TaskStatus;
	waiting_on: string | null;
	due_date: string | null;
	steps_done: number;
	steps_total: number;
}

export interface Tree {
	spaces: (Space & { projects: Project[] })[];
	pinned_tags: Tag[];
}

export interface NewEntry {
	entry_date: string;
	project_id?: string | null;
	space_id?: string | null;
	task_id?: string | null;
	kind?: EntryKind;
	title?: string;
	body?: string;
	start_time?: string | null;
	end_time?: string | null;
	source?: 'journal' | 'writing' | 'capture' | 'mail' | 'import';
	people?: string[];
	tags?: string[];
}

export interface EntryPatch {
	expected_revision: number;
	title?: string | null;
	body?: string | null;
	kind?: EntryKind;
	start_time?: string | null;
	people?: string[];
	tags?: string[];
}

const q = (params: Record<string, string | number | undefined>) =>
	Object.entries(params)
		.filter(([, v]) => v !== undefined && v !== '')
		.map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
		.join('&');

export interface ProjectView extends Project {
	links: { url: string; label: string | null }[];
	last_activity: string | null;
	open_tasks: number;
}

export const v2 = {
	project: (id: string) => request<ProjectView>('GET', `/api/v2/projects/${encodeURIComponent(id)}`),
	projectTasks: (id: string) => request<Task[]>('GET', `/api/v2/projects/${encodeURIComponent(id)}/tasks`),
	tree: () => request<Tree>('GET', '/api/v2/tree'),
	people: () => request<Person[]>('GET', '/api/v2/people'),
	timeline: (params: { day?: string; project_id?: string; person_id?: string; tag_id?: string; limit?: number }) =>
		request<Entry[]>('GET', `/api/v2/timeline?${q({ limit: 200, ...params })}`),
	journalDays: (month: string) => request<string[]>('GET', `/api/v2/journal/days?month=${month}`),
	createEntry: (entry: NewEntry) => request<Entry>('POST', '/api/v2/entries', entry),
	updateEntry: (id: string, patch: EntryPatch) => request<Entry>('PATCH', `/api/v2/entries/${id}`, patch),
	moveEntry: (id: string, to: { project_id?: string | null; space_id?: string | null }) =>
		request<Entry>('POST', `/api/v2/entries/${id}/move`, to),
	deleteEntry: (id: string) => request<void>('DELETE', `/api/v2/entries/${id}`),
	createTask: (task: { title: string; project_id?: string | null; space_id?: string | null; origin_entry_id?: string }) =>
		request<Task>('POST', '/api/v2/tasks', task)
};
