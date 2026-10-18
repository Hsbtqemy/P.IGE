<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { todayIso } from '#lib/carnet/state.svelte.js';

	onMount(() => goto(`/agenda/${todayIso()}`, { replaceState: true }));
</script>
