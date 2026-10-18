// Markdown shown formatted while writing: the signs (#, **, _, `, >) stay visible only on
// the lines being edited, like a word processor that still lets you see the source.

import { defaultKeymap, history, historyKeymap } from '@codemirror/commands';
import { markdown, markdownLanguage } from '@codemirror/lang-markdown';
import { HighlightStyle, syntaxHighlighting, syntaxTree } from '@codemirror/language';
import { EditorState, type Extension, type Range } from '@codemirror/state';
import { Decoration, type DecorationSet, EditorView, keymap, ViewPlugin, type ViewUpdate } from '@codemirror/view';
import { tags } from '@lezer/highlight';

const HIDDEN_MARKS = new Set(['HeaderMark', 'EmphasisMark', 'CodeMark', 'StrikethroughMark', 'QuoteMark']);
const hide = Decoration.replace({});

/** Lines touched by the selection: there the Markdown signs are shown. */
function activeLines(state: EditorState): Set<number> {
	const lines = new Set<number>();
	for (const range of state.selection.ranges) {
		const first = state.doc.lineAt(range.from).number;
		const last = state.doc.lineAt(range.to).number;
		for (let n = first; n <= last; n++) lines.add(n);
	}
	return lines;
}

function hiddenMarks(view: EditorView): DecorationSet {
	const { state } = view;
	const active = activeLines(state);
	const ranges: Range<Decoration>[] = [];
	for (const { from, to } of view.visibleRanges) {
		syntaxTree(state).iterate({
			from,
			to,
			enter: (node) => {
				if (!HIDDEN_MARKS.has(node.name)) return;
				if (active.has(state.doc.lineAt(node.from).number)) return;
				let end = node.to;
				// "# Titre", "> citation": the space after the sign goes too.
				if ((node.name === 'HeaderMark' || node.name === 'QuoteMark') && state.doc.sliceString(end, end + 1) === ' ') end++;
				if (end > node.from) ranges.push(hide.range(node.from, end));
			}
		});
	}
	return Decoration.set(ranges, true);
}

const marksPlugin = ViewPlugin.fromClass(
	class {
		decorations: DecorationSet;
		constructor(view: EditorView) {
			this.decorations = hiddenMarks(view);
		}
		update(update: ViewUpdate) {
			if (update.docChanged || update.viewportChanged || update.selectionSet) {
				this.decorations = hiddenMarks(update.view);
			}
		}
	},
	{ decorations: (plugin) => plugin.decorations }
);

const style = HighlightStyle.define([
	{ tag: tags.heading1, fontFamily: 'var(--serif)', fontSize: '1.75em', fontWeight: '600', lineHeight: '1.25' },
	{ tag: tags.heading2, fontFamily: 'var(--serif)', fontSize: '1.4em', fontWeight: '600', lineHeight: '1.3' },
	{ tag: tags.heading3, fontFamily: 'var(--serif)', fontSize: '1.15em', fontWeight: '600' },
	{ tag: [tags.heading4, tags.heading5, tags.heading6], fontWeight: '700' },
	{ tag: tags.emphasis, fontStyle: 'italic' },
	{ tag: tags.strong, fontWeight: '700' },
	{ tag: tags.strikethrough, textDecoration: 'line-through' },
	{ tag: tags.link, color: 'var(--accent)', textDecoration: 'underline' },
	{ tag: tags.url, color: 'var(--muted)' },
	{ tag: tags.monospace, fontFamily: 'ui-monospace, Menlo, Consolas, monospace', fontSize: '0.9em' },
	{ tag: tags.quote, color: 'var(--muted)', fontStyle: 'italic' },
	{ tag: [tags.processingInstruction, tags.meta], color: 'var(--muted)' },
	{ tag: tags.list, color: 'var(--accent)' }
]);

const theme = EditorView.theme({
	'&': { color: 'var(--ink)', backgroundColor: 'transparent', fontSize: '1.0625rem' },
	'&.cm-focused': { outline: 'none' },
	'.cm-scroller': { fontFamily: 'var(--sans)', lineHeight: '1.65' },
	'.cm-content': { padding: '8px 0 40vh', caretColor: 'var(--accent)', maxWidth: '72ch' },
	'.cm-line': { padding: '0 2px' },
	'.cm-cursor': { borderLeftColor: 'var(--accent)', borderLeftWidth: '2px' },
	'&.cm-focused .cm-selectionBackground, .cm-selectionBackground, ::selection': { backgroundColor: 'var(--soft)' }
});

export interface WritingOptions {
	onChange: (text: string) => void;
	onSave: () => void;
}

export function writingExtensions({ onChange, onSave }: WritingOptions): Extension[] {
	return [
		history(),
		keymap.of([{ key: 'Mod-s', preventDefault: true, run: () => (onSave(), true) }, ...defaultKeymap, ...historyKeymap]),
		markdown({ base: markdownLanguage }),
		syntaxHighlighting(style),
		marksPlugin,
		theme,
		EditorView.lineWrapping,
		EditorView.contentAttributes.of({ 'aria-label': 'Texte', spellcheck: 'true', lang: 'fr' }),
		EditorView.updateListener.of((update) => {
			if (update.docChanged) onChange(update.state.doc.toString());
		})
	];
}

export interface Heading {
	level: number;
	text: string;
	line: number;
}

/** The plan: « # », « ## », « ### » headings, outside code blocks. */
export function outline(text: string): Heading[] {
	const out: Heading[] = [];
	let fence = false;
	text.split('\n').forEach((line, i) => {
		if (/^\s*(```|~~~)/.test(line)) fence = !fence;
		if (fence) return;
		const m = line.match(/^(#{1,3})\s+(.+?)\s*#*\s*$/);
		if (m) out.push({ level: m[1].length, text: m[2].replace(/[*_`]/g, ''), line: i + 1 });
	});
	return out;
}
