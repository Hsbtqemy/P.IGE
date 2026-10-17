<script lang="ts">
	import '@fontsource/atkinson-hyperlegible-next/latin-400.css';
	import '@fontsource/atkinson-hyperlegible-next/latin-700.css';
	import '../app.css';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();
</script>

{@render children()}
