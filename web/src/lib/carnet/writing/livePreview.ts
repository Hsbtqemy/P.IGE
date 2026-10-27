// Markdown shown formatted while writing: the signs (#, **, _, `, >) stay visible only on
// the lines being edited, like a word processor that still lets you see the source. Lists get
// bullets, and « - [ ] » becomes a box that a click ticks (« - [x] », the line struck through).

import { defaultKeymap, history, historyKeymap } from '@codemirror/commands';
import { markdown, markdownLanguage } from '@codemirror/lang-markdown';
import { HighlightStyle, syntaxHighlighting, syntaxTree } from '@codemirror/language';
import { EditorState, type Extension, type Range } from '@codemirror/state';
import { Decoration, type DecorationSet, EditorView, keymap, ViewPlugin, type ViewUpdate, WidgetType } from '@codemirror/view';
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

export type ToggleHandler = (title: string, done: boolean) => void;

/** « - [ ] text » at the start of a line: the sign and box, then the text. */
const TASK_LINE = /^(\s*)([-*+])\s+\[([ xX])\]\s+/;

/** Tick or untick the box at ``pos`` (the « [ ] »), then tell who listens. */
function toggleBox(view: EditorView, pos: number, onToggle?: ToggleHandler): boolean {
	const mark = view.state.doc.sliceString(pos, pos + 3);
	if (!/^\[[ xX]\]$/.test(mark)) return false;
	const done = mark === '[ ]';
	view.dispatch({ changes: { from: pos + 1, to: pos + 2, insert: done ? 'x' : ' ' } });
	const line = view.state.doc.lineAt(pos);
	const title = line.text.replace(TASK_LINE, '').trim();
	if (title) onToggle?.(title, done);
	return true;
}

class BoxWidget extends WidgetType {
	constructor(
		readonly checked: boolean,
		readonly pos: number,
		readonly onToggle?: ToggleHandler
	) {
		super();
	}
	eq(other: BoxWidget) {
		return other.checked === this.checked && other.pos === this.pos;
	}
	toDOM(view: EditorView) {
		const box = document.createElement('input');
		box.type = 'checkbox';
		box.checked = this.checked;
		box.className = 'cm-box';
		box.setAttribute('aria-label', this.checked ? 'Décocher' : 'Cocher');
		box.addEventListener('mousedown', (e) => e.preventDefault());
		box.addEventListener('click', (e) => {
			e.preventDefault();
			toggleBox(view, this.pos, this.onToggle);
		});
		return box;
	}
	ignoreEvent() {
		return true;
	}
}

class BulletWidget extends WidgetType {
	eq() {
		return true;
	}
	toDOM() {
		const dot = document.createElement('span');
		dot.className = 'cm-bullet';
		dot.textContent = '•';
		return dot;
	}
}
const bullet = new BulletWidget();
const doneLine = Decoration.line({ class: 'cm-task-done' });

function hiddenMarks(view: EditorView, onToggle?: ToggleHandler): DecorationSet {
	const { state } = view;
	const active = activeLines(state);
	const ranges: Range<Decoration>[] = [];
	for (const { from, to } of view.visibleRanges) {
		syntaxTree(state).iterate({
			from,
			to,
			enter: (node) => {
				if (node.name === 'TaskMarker') {
					const line = state.doc.lineAt(node.from);
					const checked = state.doc.sliceString(node.from + 1, node.from + 2) !== ' ';
					if (checked) ranges.push(doneLine.range(line.from));
					const m = line.text.match(TASK_LINE);
					if (m && !active.has(line.number)) {
						const start = line.from + m[1].length;
						ranges.push(Decoration.replace({ widget: new BoxWidget(checked, node.from, onToggle) }).range(start, line.from + m[0].length));
					}
					return;
				}
				if (node.name === 'ListMark' && node.node.parent?.parent?.name === 'BulletList') {
					const line = state.doc.lineAt(node.from);
					if (active.has(line.number) || TASK_LINE.test(line.text)) return;
					ranges.push(Decoration.replace({ widget: bullet }).range(node.from, node.to));
					return;
				}
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

function marksPlugin(onToggle?: ToggleHandler) {
	return ViewPlugin.fromClass(
		class {
			decorations: DecorationSet;
			constructor(view: EditorView) {
				this.decorations = hiddenMarks(view, onToggle);
			}
			update(update: ViewUpdate) {
				if (update.docChanged || update.viewportChanged || update.selectionSet) {
					this.decorations = hiddenMarks(update.view, onToggle);
				}
			}
		},
		{ decorations: (plugin) => plugin.decorations }
	);
}

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
	{ tag: [tags.processingInstruction, tags.meta], color: 'var(--muted)' }
]);

const theme = EditorView.theme({
	'&': { color: 'var(--ink)', backgroundColor: 'transparent', fontSize: '1.0625rem' },
	'&.cm-focused': { outline: 'none' },
	'.cm-scroller': { fontFamily: 'var(--sans)', lineHeight: '1.65' },
	'.cm-content': { padding: '8px 0 40vh', caretColor: 'var(--accent)', maxWidth: '72ch' },
	'.cm-line': { padding: '0 2px' },
	'.cm-cursor': { borderLeftColor: 'var(--accent)', borderLeftWidth: '2px' },
	'.cm-box': { margin: '0 0.45em 0 0', verticalAlign: '-0.1em', cursor: 'pointer', accentColor: 'var(--accent)' },
	'.cm-bullet': { color: 'var(--accent)', fontWeight: '700' },
	'.cm-task-done': { color: 'var(--muted)', textDecoration: 'line-through' },
	'&.cm-focused .cm-selectionBackground, .cm-selectionBackground, ::selection': { backgroundColor: 'var(--soft)' }
});

export interface WritingOptions {
	onChange: (text: string) => void;
	onSave: () => void;
	onToggle?: ToggleHandler;
}

export function writingExtensions({ onChange, onSave, onToggle }: WritingOptions): Extension[] {
	return [
		history(),
		keymap.of([{ key: 'Mod-s', preventDefault: true, run: () => (onSave(), true) }, ...defaultKeymap, ...historyKeymap]),
		markdown({ base: markdownLanguage }),
		syntaxHighlighting(style),
		marksPlugin(onToggle),
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
