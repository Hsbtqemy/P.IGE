<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { EditorState } from '@codemirror/state';
	import { EditorView } from '@codemirror/view';
	import { writingExtensions } from './livePreview.js';

	let {
		value,
		onchange,
		onsave,
		ontoggle,
		onimages
	}: {
		value: string;
		onchange: (text: string) => void;
		onsave: () => void;
		ontoggle?: (title: string, done: boolean) => void; // a box ticked in the text
		onimages?: (files: File[], pos: number) => void; // images pasted or dropped
	} = $props();

	let host: HTMLDivElement;
	let view: EditorView | null = null;

	onMount(() => {
		view = new EditorView({
			parent: host,
			state: EditorState.create({
				doc: value,
				extensions: writingExtensions({
					onChange: (text) => onchange(text),
					onSave: () => onsave(),
					onToggle: (title, done) => ontoggle?.(title, done),
					onImages: (files, pos) => onimages?.(files, pos)
				})
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

	/** Put text at a position (an image's Markdown), on a line of its own, cursor after it. */
	export function insertAt(pos: number, text: string) {
		if (!view) return;
		const doc = view.state.doc;
		const at = Math.min(Math.max(pos, 0), doc.length);
		const line = doc.lineAt(at);
		const before = line.text.trim() && at > line.from ? '\n' : '';
		const after = at < line.to || !doc.sliceString(at, at + 1).startsWith('\n') ? '\n' : '';
		const insert = `${before}${text}${after}`;
		view.dispatch({ changes: { from: at, insert }, selection: { anchor: at + insert.length } });
		view.focus();
	}

	/** Where the cursor is (to insert an image chosen from a button). */
	export function cursor(): number {
		return view?.state.selection.main.head ?? 0;
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
