<script lang="ts">
	// « Ouvrir le mail »: in Thunderbird through the extension's bridge, else in Apple Mail
	// (message:// link) on a Mac, iPhone or iPad. Nothing elsewhere.
	import { appleMail, appleMailHref, openMail, thunderbird } from './thunderbird.svelte.js';

	let { messageId, class: cls = 'btn', label = '✉ Ouvrir le mail' }: { messageId: string; class?: string; label?: string } = $props();
</script>

{#if thunderbird.available}
	<button class={cls} onclick={() => openMail(messageId)} title="Ouvrir le mail dans Thunderbird">{label}</button>
{:else if appleMail}
	<a class={cls} href={appleMailHref(messageId)} title="Ouvrir le mail dans Mail">{label}</a>
{/if}
