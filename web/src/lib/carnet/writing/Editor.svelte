<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { EditorState } from '@codemirror/state';
	import { EditorView } from '@codemirror/view';
	import { writingExtensions } from './livePreview.js';

	let {
		value,
		onchange,
		onsave
	}: { value: string; onchange: (text: string) => void; onsave: () => void } = $props();

	let host: HTMLDivElement;
	let view: EditorView | null = null;

	onMount(() => {
		view = new EditorView({
			parent: host,
			state: EditorState.create({
				doc: value,
				extensions: writingExtensions({ onChange: (text) => onchange(text), onSave: () => onsave() })
			})
		});
	});

	onDestroy(() => view?.destroy());

	/** Replace the whole text (a restored version, the other device's text). */
	export function setText(text: string) {
		if (!view || view.state.doc.toString() === text) return;
		view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: text } });
	}

	/** Put the cursor at the start of a line and bring it into view. */
	export function jump(line: number) {
		if (!view) return;
		const target = view.state.doc.line(Math.min(Math.max(line, 1), view.state.doc.lines));
		view.dispatch({ selection: { anchor: target.from }, effects: EditorView.scrollIntoView(target.from, { y: 'start', yMargin: 24 }) });
		view.focus();
	}

	export function focus() {
		view?.focus();
	}
</script>

<div class="editor" bind:this={host}></div>

<style>
	.editor {
		min-height: 60vh;
	}
</style>
