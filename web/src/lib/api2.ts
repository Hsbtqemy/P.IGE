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
	source: 'journal' | 'writing' | 'capture' | 'mail' | 'import';
	mail_message_id?: string | null;
	created_at: string;
	updated_at: string;
	version: number;
	revision: number;
	cancelled?: boolean;
	people: Person[];
	tags: Tag[];
	/** A code day (code journal): the day's commits by work item. */
	code?: CodeDay;
}

export interface Chantier {
	code: string;
	title: string;
	status: string;
	stopped: string;
	stopped_label: string;
	open: number;
	path: string;
	/** Date of its last commit (AAAA-MM-JJ), when known. */
	last?: string;
}

/** A day of pushed code, summed up by work item (« chantier » of pilote). */
export interface CodeDay {
	total: number;
	chantiers: { code: string; title: string; count: number; stopped: string; path: string }[];
	other: number;
	repo: string | null;
	branch: string | null;
}

export interface ProjectCode {
	repo: string | null;
	export_url?: string | null;
	/** The repository sends its journal itself (« pilote envoyer », npm run pige). */
	pushed?: boolean;
	token: boolean;
	branch?: string | null;
	last_sync?: string | null;
	last_error?: string | null;
	chantiers?: Chantier[];
	closed?: number;
}

export interface EntryVersion {
	entry_id: string;
	version: number;
	title: string;
	body: string;
	saved_at: string;
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
	done_at?: string | null;
	status_since?: string;
	origin_entry_id?: string | null;
	created_at?: string;
	steps_done: number;
	steps_total: number;
}

export interface PersonView extends Person {
	note: string | null;
	tags: Tag[];
	last_exchange: string | null;
	waiting_on: Task[];
	involved_in: Task[];
	projects: (Project & { project_role: string | null })[];
}

export interface PersonPatch {
	display_name?: string;
	email?: string | null;
	organisation?: string | null;
	role?: string | null;
	note?: string | null;
	tags?: string[];
}

export interface TagView extends Tag {
	people: Person[];
	tasks: Task[];
}

export interface TaskMail {
	id: string;
	task_id: string;
	entry_id: string | null;
	day: string;
	message_id: string;
	direction: 'sent' | 'received';
	sent_at: string;
	author: string;
	recipients: string;
	subject: string;
	body: string;
	attachments: string;
}

export interface Step {
	id: string;
	task_id: string;
	label: string;
	done: boolean;
	position: number;
}

export interface TaskView extends Task {
	steps: Step[];
	people: Person[];
	tags: Tag[];
}

export interface TaskPatch {
	title?: string;
	note?: string | null;
	due_date?: string;
	status?: TaskStatus;
	waiting_on?: string;
	person_ids?: string[];
}

export interface ProjectPatch {
	name?: string;
	description?: string | null;
	team?: string | null;
	state?: Project['state'];
}

/** Relative position in a list: exactly one of the two. */
export type Place = { before: string } | { after: string };

export type OverlapMode = 'shared' | 'both' | 'exclusive';

export interface TimeBlock {
	id: string;
	space_id: string;
	project_id: string | null;
	task_id: string | null;
	entry_id: string | null;
	start_at: string;
	end_at: string | null;
	source: 'timer' | 'agenda' | 'manual';
	overlap_mode: OverlapMode;
	note: string | null;
	validated: boolean;
}

export interface CountedBlock {
	block: TimeBlock;
	start: string;
	end: string;
	counted_seconds: number;
	running: boolean;
}

export interface DayReport {
	day: string;
	presence_seconds: number;
	by_space: Record<string, number>;
	by_project: Record<string, number>;
	blocks: CountedBlock[];
	stale_timers: TimeBlock[];
}

export interface WeekReport {
	start: string;
	end: string;
	presence_seconds: number;
	span_seconds: number;
	days: {
		day: string;
		presence_seconds: number;
		counted_seconds: number;
		span_seconds: number | null;
		span_estimated: boolean | null;
	}[];
	by_space: Record<string, number>;
	by_project: Record<string, number>;
}

export interface Priority {
	text: string;
	task_id: string | null;
	done: boolean;
	carried?: boolean;
	task_status?: string | null;
}

export interface DaySpan {
	start: string;
	end: string;
	seconds: number;
	estimated: boolean;
}

export interface DayFrame {
	day: string;
	started_at: string | null;
	ended_at: string | null;
	priorities: Priority[];
	tomorrow: string;
	from_before: { day: string; text: string } | null;
	span: DaySpan | null;
}

export interface FramePatch {
	started_at?: string | null;
	ended_at?: string | null;
	priorities?: { text: string; task_id: string | null; done: boolean; carried?: boolean }[];
	tomorrow?: string;
}

export interface Target {
	project_id?: string | null;
	space_id?: string | null;
	task_id?: string | null;
}

export interface SearchHit {
	kind: 'entry' | 'task';
	id: string;
	title: string;
	snippet: string;
	space_id: string;
	project_id: string | null;
	entry_date: string | null;
	status: TaskStatus | null;
	done_at?: string | null;
}

export interface CalendarInfo {
	id: string;
	name: string;
	color: string;
	host: string;
	has_password: boolean;
	project_id: string | null;
	active: boolean;
	last_sync: string | null;
	last_error: string | null;
}

export type SyncResult = { ok: true; added: number; updated: number; removed: number } | { ok: false; error: string };

export interface CalendarInput {
	name?: string;
	url?: string;
	username?: string | null;
	password?: string | null;
	color?: string;
	project_id?: string | null;
	active?: boolean;
}

export interface AgendaEvent {
	id: string;
	calendar_id: string;
	calendar: string;
	color: string;
	/** UTC « …Z » for timed events, « AAAA-MM-JJ » for all-day ones. */
	start: string;
	end: string;
	all_day: boolean;
	title: string;
	location: string | null;
	description: string | null;
	organizer: string | null;
	attendees: { name: string; email: string }[];
	status: string | null;
	entry_id: string | null;
	block_id: string | null;
	project_id: string | null;
	/** Where the note (else the counted time) is filed, once noted or counted. */
	place: { project_id: string | null; space_id: string } | null;
	/** filed: its note or time; event / series: chosen before any note; null: the default. */
	place_source: 'filed' | 'event' | 'series' | null;
	recurring: boolean;
	series_filed: boolean;
}

export interface Tree {
	spaces: (Space & { projects: Project[] })[];
	pinned_tags: Tag[];
}

export interface NewEntry {
	/** Chosen on the device (32 hex): sending again after a lost reply returns the same entry. */
	id?: string;
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
	autosave?: boolean;
	entry_date?: string;
	title?: string | null;
	body?: string | null;
	kind?: EntryKind;
	start_time?: string | null;
	end_time?: string | null;
	cancelled?: boolean;
	people?: string[];
	tags?: string[];
}

const q = (params: Record<string, string | number | boolean | undefined>) =>
	Object.entries(params)
		.filter(([, v]) => v !== undefined && v !== '')
		.map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
		.join('&');

export interface ProjectView extends Project {
	links: { url: string; label: string | null }[];
	last_activity: string | null;
	open_tasks: number;
	/** Its people, then those of its parent project (« inherited »: shown, not copied). */
	people: (Person & { project_role: string | null; inherited: boolean })[];
}

export const v2 = {
	project: (id: string) => request<ProjectView>('GET', `/api/v2/projects/${encodeURIComponent(id)}`),
	projectTasks: (id: string, includeDone = false) =>
		request<Task[]>('GET', `/api/v2/projects/${encodeURIComponent(id)}/tasks${includeDone ? '?include_done=true' : ''}`),
	updateProject: (id: string, patch: ProjectPatch) =>
		request<ProjectView>('PATCH', `/api/v2/projects/${encodeURIComponent(id)}`, patch),
	task: (id: string) => request<TaskView>('GET', `/api/v2/tasks/${id}`),
	updateTask: (id: string, patch: TaskPatch) => request<TaskView>('PATCH', `/api/v2/tasks/${id}`, patch),
	placeTask: (id: string, place: Place) => request<void>('POST', `/api/v2/tasks/${id}/place`, place),
	deleteTask: (id: string) => request<void>('DELETE', `/api/v2/tasks/${id}`),
	addStep: (taskId: string, label: string) => request<Step>('POST', `/api/v2/tasks/${taskId}/steps`, { label }),
	updateStep: (id: string, done: boolean) => request<Step>('PATCH', `/api/v2/steps/${id}`, { done }),
	placeStep: (id: string, place: Place) => request<void>('POST', `/api/v2/steps/${id}/place`, place),
	deleteStep: (id: string) => request<void>('DELETE', `/api/v2/steps/${id}`),
	timers: () => request<TimeBlock[]>('GET', '/api/v2/timers'),
	startTimer: (target: Target & { note?: string | null }) => request<TimeBlock>('POST', '/api/v2/timers', target),
	stopTimer: (id: string, at?: string) => request<TimeBlock>('POST', `/api/v2/timers/${id}/stop`, at ? { at } : {}),
	addBlock: (block: Target & { start: string; end: string; note?: string | null; overlap_mode?: OverlapMode }) =>
		request<TimeBlock>('POST', '/api/v2/blocks', block),
	updateBlock: (
		id: string,
		patch: Target & { start?: string; end?: string | null; note?: string | null; overlap_mode?: OverlapMode }
	) => request<TimeBlock>('PATCH', `/api/v2/blocks/${id}`, patch),
	deleteBlock: (id: string) => request<void>('DELETE', `/api/v2/blocks/${id}`),
	day: (day: string, tz: string) => request<DayReport>('GET', `/api/v2/days/${day}?tz=${encodeURIComponent(tz)}`),
	frame: (day: string, tz: string) => request<DayFrame>('GET', `/api/v2/days/${day}/frame?tz=${encodeURIComponent(tz)}`),
	updateFrame: (day: string, tz: string, patch: FramePatch) =>
		request<DayFrame>('PATCH', `/api/v2/days/${day}/frame?tz=${encodeURIComponent(tz)}`, patch),
	planned: (start: string, days: number, tz: string) =>
		request<Entry[]>('GET', `/api/v2/planned?start=${start}&days=${days}&tz=${encodeURIComponent(tz)}`),
	week: (day: string, tz: string) => request<WeekReport>('GET', `/api/v2/weeks/${day}?tz=${encodeURIComponent(tz)}`),
	validateDay: (day: string, tz: string) =>
		request<{ validated: number }>('POST', `/api/v2/days/${day}/validate?tz=${encodeURIComponent(tz)}`),
	search: (text: string, limit = 20) => request<SearchHit[]>('GET', `/api/v2/search?${q({ q: text, limit, include_done: true })}`),
	linkedRepos: () =>
		request<{ project_id: string; repo: string; last_sync: string | null; last_error: string | null }[]>('GET', '/api/v2/code'),
	syncAllCode: () =>
		request<{ repos: number; days: number; pushed: number; errors: { repo: string; error: string }[] }>(
			'POST',
			'/api/v2/code/sync'
		),
	projectCode: (id: string) => request<ProjectCode>('GET', `/api/v2/projects/${encodeURIComponent(id)}/code`),
	setProjectRepo: (id: string, repo: string | null, export_url: string | null = null) =>
		request<ProjectCode>('PUT', `/api/v2/projects/${encodeURIComponent(id)}/repo`, { repo, export_url }),
	syncProjectCode: (id: string) => request<ProjectCode>('POST', `/api/v2/projects/${encodeURIComponent(id)}/code/sync`),
	taskMails: (taskId: string) => request<TaskMail[]>('GET', `/api/v2/tasks/${encodeURIComponent(taskId)}/mails`),
	addFollowUp: (taskId: string, entry_date: string, body: string) =>
		request<Entry>('POST', `/api/v2/tasks/${encodeURIComponent(taskId)}/followups`, { entry_date, body }),
	deleteTaskMail: (id: string) => request<void>('DELETE', `/api/v2/task-mails/${encodeURIComponent(id)}`),
	doneTasks: (since: string) => request<Task[]>('GET', `/api/v2/tasks/done?${q({ since })}`),
	openTasks: (living = false) => request<Task[]>('GET', `/api/v2/tasks${living ? '?living=true' : ''}`),
	calendars: () => request<CalendarInfo[]>('GET', '/api/v2/calendars'),
	addCalendar: (input: CalendarInput & { name: string; url: string }) =>
		request<{ calendar: CalendarInfo; sync: SyncResult }>('POST', '/api/v2/calendars', input),
	updateCalendar: (id: string, input: CalendarInput) =>
		request<{ calendar: CalendarInfo; sync: SyncResult | null }>('PATCH', `/api/v2/calendars/${id}`, input),
	deleteCalendar: (id: string) => request<void>('DELETE', `/api/v2/calendars/${id}`),
	syncCalendar: (id: string) => request<SyncResult>('POST', `/api/v2/calendars/${id}/sync`),
	agenda: (start: string, days: number, tz: string) =>
		request<AgendaEvent[]>('GET', `/api/v2/agenda?${q({ start, days, tz })}`),
	noteEvent: (id: string, target: Target, tz: string) =>
		request<{ entry_id: string; created: boolean; event: AgendaEvent }>('POST', `/api/v2/agenda/${id}/note?${q({ tz })}`, target),
	placeEvent: (id: string, target: Target, series = false) =>
		request<AgendaEvent>('POST', `/api/v2/agenda/${encodeURIComponent(id)}/place`, { ...target, series }),
	countEvent: (id: string, target: Target) =>
		request<{ block_id: string; created: boolean; event: AgendaEvent }>('POST', `/api/v2/agenda/${id}/count`, target),
	tasksInProgress: () => request<Task[]>('GET', '/api/v2/tasks/in-progress'),
	personView: (id: string) => request<PersonView>('GET', `/api/v2/people/${encodeURIComponent(id)}`),
	updatePerson: (id: string, patch: PersonPatch) => request<PersonView>('PATCH', `/api/v2/people/${id}`, patch),
	deletePerson: (id: string) => request<void>('DELETE', `/api/v2/people/${id}`),
	peopleWithTag: (tagId: string) => request<Person[]>('GET', `/api/v2/people?tag_id=${tagId}`),
	tags: () => request<Tag[]>('GET', '/api/v2/tags'),
	tag: (id: string) => request<TagView>('GET', `/api/v2/tags/${encodeURIComponent(id)}`),
	pinTag: (id: string, pinned: boolean) => request<Tag>('PATCH', `/api/v2/tags/${id}`, { pinned }),
	person: (name: string) => request<Person>('POST', '/api/v2/people', { name }),
	setProjectPerson: (projectId: string, personId: string, role: string | null) =>
		request<ProjectView>('PUT', `/api/v2/projects/${encodeURIComponent(projectId)}/people/${encodeURIComponent(personId)}`, { role }),
	removeProjectPerson: (projectId: string, personId: string) =>
		request<ProjectView>('DELETE', `/api/v2/projects/${encodeURIComponent(projectId)}/people/${encodeURIComponent(personId)}`),
	tree: (includeArchived = false) => request<Tree>('GET', `/api/v2/tree${includeArchived ? '?include_archived=true' : ''}`),
	createSpace: (name: string) => request<Space>('POST', '/api/v2/spaces', { name }),
	updateSpace: (id: string, patch: { name?: string; archived?: boolean }) =>
		request<Space>('PATCH', `/api/v2/spaces/${encodeURIComponent(id)}`, patch),
	placeSpace: (id: string, place: Place) => request<void>('POST', `/api/v2/spaces/${id}/place`, place),
	deleteSpace: (id: string) => request<void>('DELETE', `/api/v2/spaces/${id}`),
	createProject: (project: { space_id: string; name: string; parent_id?: string | null; team?: string | null }) =>
		request<ProjectView>('POST', '/api/v2/projects', project),
	moveProject: (id: string, to: { space_id: string; parent_id: string | null }) =>
		request<ProjectView>('POST', `/api/v2/projects/${id}/move`, to),
	placeProject: (id: string, place: Place) => request<void>('POST', `/api/v2/projects/${id}/place`, place),
	deleteProject: (id: string) => request<void>('DELETE', `/api/v2/projects/${id}`),
	people: () => request<Person[]>('GET', '/api/v2/people'),
	timeline: (params: {
		day?: string;
		space_id?: string;
		project_id?: string;
		person_id?: string;
		tag_id?: string;
		task_id?: string;
		source?: Entry['source'];
		without_project?: boolean;
		limit?: number;
		offset?: number;
	}) =>
		request<Entry[]>('GET', `/api/v2/timeline?${q({ limit: 200, ...params })}`),
	journalDays: (month: string) => request<string[]>('GET', `/api/v2/journal/days?month=${month}`),
	createEntry: (entry: NewEntry) => request<Entry>('POST', '/api/v2/entries', entry),
	entryTasks: (id: string) => request<Task[]>('GET', `/api/v2/entries/${id}/tasks`),
	updateEntry: (id: string, patch: EntryPatch) => request<Entry>('PATCH', `/api/v2/entries/${id}`, patch),
	spaceTasks: (id: string) => request<Task[]>('GET', `/api/v2/spaces/${encodeURIComponent(id)}/tasks`),
	renameSpace: (id: string, name: string) => request<Space>('PATCH', `/api/v2/spaces/${encodeURIComponent(id)}`, { name }),
	moveTask: (id: string, to: { project_id?: string | null; space_id?: string | null }) =>
		request<TaskView>('POST', `/api/v2/tasks/${id}/move`, to),
	moveEntry: (id: string, to: { project_id?: string | null; space_id?: string | null }) =>
		request<Entry>('POST', `/api/v2/entries/${id}/move`, to),
	entry: (id: string) => request<Entry>('GET', `/api/v2/entries/${encodeURIComponent(id)}`),
	entryVersions: (id: string) => request<EntryVersion[]>('GET', `/api/v2/entries/${id}/versions?limit=50`),
	deleteEntry: (id: string) => request<void>('DELETE', `/api/v2/entries/${id}`),
	createTask: (task: {
		id?: string;
		title: string;
		project_id?: string | null;
		space_id?: string | null;
		origin_entry_id?: string;
	}) =>
		request<Task>('POST', '/api/v2/tasks', task)
};
