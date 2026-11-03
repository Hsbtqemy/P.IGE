<script lang="ts">
	// The address of the site (and of the app installed on a phone) opens Ma journée.
	// The first capture screen that lived here is gone: « Noter » does its job.
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';

	onMount(() => {
		const now = new Date();
		const today = new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
		void goto(`/journee/${today}`, { replaceState: true });
	});
</script>

<svelte:head><title>P.IGE</title></svelte:head>
