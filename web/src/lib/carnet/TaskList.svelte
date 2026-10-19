<script lang="ts">
	import type { Task } from '../api2.js';
	import { carnet, placeName } from './state.svelte.js';

	let { tasks, empty = 'Aucune tâche.' }: { tasks: Task[]; empty?: string } = $props();

	function since(task: Task): string {
		const iso = task.status_since;
		if (!iso) return '';
		const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
		return days < 1 ? 'aujourd’hui' : days === 1 ? 'depuis hier' : `depuis ${days} jours`;
	}

	function waitingName(task: Task): string {
		return carnet.people.find((p) => p.id === task.waiting_on)?.display_name ?? '';
	}
</script>

{#each tasks as task (task.id)}
	<a class="task" href="{task.project_id ? `/projets/${task.project_id}` : `/espaces/${task.space_id}`}?tache={task.id}">
		<span class="title">{task.title}</span>
		<small>
			{placeName(task)}
			{#if task.status === 'in_progress'} · <span class="doing">en cours</span>{/if}
			{#if task.status === 'waiting'} · attend {waitingName(task)} {since(task)}{/if}
			{#if task.due_date} · pour le {new Date(`${task.due_date}T12:00:00`).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' })}{/if}
		</small>
	</a>
{:else}
	<p class="muted">{empty}</p>
{/each}

<style>
	.task {
		display: flex;
		flex-direction: column;
		padding: 8px 0;
		border-bottom: 1px solid var(--line);
		text-decoration: none;
	}
	.title {
		font-weight: 700;
	}
	small,
	.muted {
		font-size: 0.875rem;
		color: var(--muted);
	}
	.doing {
		color: var(--accent);
		font-weight: 700;
	}
</style>
