// language: JavaScript, file: entry.js, target: browser (bundled by esbuild)
// Jarvis editor bundle. Exports one factory + a language picker, so stage.html
// never touches CodeMirror internals — it hands over a DOM node and a string.

import {
  EditorState, Compartment
} from "@codemirror/state";
import {
  EditorView, keymap, highlightActiveLine, highlightActiveLineGutter,
  lineNumbers, drawSelection, dropCursor, rectangularSelection,
  crosshairCursor, highlightSpecialChars
} from "@codemirror/view";
import {
  defaultKeymap, history, historyKeymap, indentWithTab
} from "@codemirror/commands";
import {
  bracketMatching, foldGutter, foldKeymap, indentOnInput,
  syntaxHighlighting, HighlightStyle
} from "@codemirror/language";
import {
  searchKeymap, highlightSelectionMatches
} from "@codemirror/search";
import {
  autocompletion, completionKeymap, closeBrackets, closeBracketsKeymap
} from "@codemirror/autocomplete";
import { tags } from "@lezer/highlight";

import { python } from "@codemirror/lang-python";
import { javascript } from "@codemirror/lang-javascript";
import { json } from "@codemirror/lang-json";
import { html } from "@codemirror/lang-html";
import { css } from "@codemirror/lang-css";
import { markdown } from "@codemirror/lang-markdown";

// The HUD palette. These are literal values, not CSS variables, because
// CodeMirror injects its theme through constructed stylesheets where a var()
// reference would resolve against the sheet's own scope, not the stage's.
const INK      = "#e6dcff";
const INK_DIM  = "#a99cd0";
const INK_FAINT= "#6f6494";
const LINE     = "rgba(150,120,220,.10)";
const LINE_HARD= "rgba(150,120,220,.22)";
const SEL      = "rgba(150,110,255,.22)";

const hudTheme = EditorView.theme({
  "&": {
    color: INK,
    backgroundColor: "transparent",
    fontSize: "12.5px",
    height: "100%"
  },
  ".cm-scroller": {
    fontFamily: '"JetBrains Mono", "Cascadia Code", Consolas, monospace',
    lineHeight: "1.62",
    overflow: "auto"
  },
  ".cm-content": { caretColor: INK },
  ".cm-cursor, .cm-dropCursor": { borderLeftColor: INK, borderLeftWidth: "1.5px" },
  "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection": {
    backgroundColor: SEL
  },
  ".cm-activeLine": { backgroundColor: "rgba(150,120,220,.045)" },
  ".cm-gutters": {
    backgroundColor: "transparent",
    color: INK_FAINT,
    border: "none",
    borderRight: `1px solid ${LINE}`
  },
  ".cm-activeLineGutter": { backgroundColor: "transparent", color: INK_DIM },
  ".cm-lineNumbers .cm-gutterElement": { padding: "0 10px 0 6px", minWidth: "34px" },
  ".cm-foldGutter .cm-gutterElement": { padding: "0 4px", color: INK_FAINT },
  ".cm-foldPlaceholder": {
    backgroundColor: "rgba(150,120,220,.12)",
    border: `1px solid ${LINE_HARD}`,
    color: INK_DIM,
    borderRadius: "2px",
    padding: "0 5px"
  },
  ".cm-matchingBracket, .cm-nonmatchingBracket": {
    backgroundColor: "rgba(150,120,220,.22)",
    outline: `1px solid ${LINE_HARD}`
  },
  ".cm-selectionMatch": { backgroundColor: "rgba(150,120,220,.15)" },
  ".cm-searchMatch": { backgroundColor: "rgba(255,179,64,.22)", outline: `1px solid rgba(255,179,64,.45)` },
  ".cm-searchMatch.cm-searchMatch-selected": { backgroundColor: "rgba(255,179,64,.42)" },
  ".cm-panels": {
    backgroundColor: "rgba(12,8,26,.97)",
    color: INK_DIM,
    borderTop: `1px solid ${LINE_HARD}`
  },
  ".cm-panels input, .cm-panels button": {
    background: "rgba(150,120,220,.08)",
    border: `1px solid ${LINE_HARD}`,
    color: INK,
    fontFamily: "inherit",
    fontSize: "11px",
    padding: "3px 7px",
    borderRadius: "2px"
  },
  ".cm-panels button:hover": { background: "rgba(150,120,220,.18)" },
  ".cm-tooltip": {
    backgroundColor: "rgba(12,8,26,.98)",
    border: `1px solid ${LINE_HARD}`,
    color: INK
  },
  ".cm-tooltip-autocomplete ul li[aria-selected]": {
    backgroundColor: "rgba(150,110,255,.26)",
    color: INK
  },
  ".cm-placeholder": { color: INK_FAINT }
}, { dark: true });

const hudHighlight = HighlightStyle.define([
  { tag: tags.comment,        color: "#6f6494", fontStyle: "italic" },
  { tag: tags.lineComment,    color: "#6f6494", fontStyle: "italic" },
  { tag: tags.blockComment,   color: "#6f6494", fontStyle: "italic" },
  { tag: tags.keyword,        color: "#c8a4ff", fontWeight: "600" },
  { tag: tags.controlKeyword, color: "#c8a4ff", fontWeight: "600" },
  { tag: tags.moduleKeyword,  color: "#c8a4ff", fontWeight: "600" },
  { tag: tags.operatorKeyword,color: "#c8a4ff" },
  { tag: tags.definitionKeyword, color: "#c8a4ff", fontWeight: "600" },
  { tag: tags.string,         color: "#8fd8b0" },
  { tag: tags.special(tags.string), color: "#8fd8b0" },
  { tag: tags.regexp,         color: "#8fd8b0" },
  { tag: tags.number,         color: "#ffb340" },
  { tag: tags.bool,           color: "#ffb340" },
  { tag: tags.null,           color: "#ffb340" },
  { tag: tags.function(tags.variableName), color: "#7fd4ff" },
  { tag: tags.function(tags.propertyName), color: "#7fd4ff" },
  { tag: tags.definition(tags.variableName), color: "#e6dcff" },
  { tag: tags.className,      color: "#7fd4ff", fontWeight: "600" },
  { tag: tags.typeName,       color: "#7fd4ff" },
  { tag: tags.propertyName,   color: "#b8a8e8" },
  { tag: tags.attributeName,  color: "#b8a8e8" },
  { tag: tags.tagName,        color: "#c8a4ff" },
  { tag: tags.operator,       color: "#a99cd0" },
  { tag: tags.punctuation,    color: "#8d82b0" },
  { tag: tags.bracket,        color: "#8d82b0" },
  { tag: tags.variableName,   color: INK },
  { tag: tags.self,           color: "#ff9ed8", fontStyle: "italic" },
  { tag: tags.heading,        color: "#c8a4ff", fontWeight: "700" },
  { tag: tags.emphasis,       fontStyle: "italic", color: INK },
  { tag: tags.strong,         fontWeight: "700", color: "#ffffff" },
  { tag: tags.link,           color: "#7fd4ff", textDecoration: "underline" },
  { tag: tags.invalid,        color: "#ff6b8a" }
]);

// language id -> factory. `.ext` names are what the FILES panel already hands
// over, so the mapping is by extension and not by mimetype guesswork.
const LANGS = {
  python: () => python(),
  py:     () => python(),
  javascript: () => javascript(),
  js:     () => javascript(),
  jsx:    () => javascript({ jsx: true }),
  mjs:    () => javascript(),
  cjs:    () => javascript(),
  json:   () => json(),
  html:   () => html(),
  htm:    () => html(),
  css:    () => css(),
  scss:   () => css(),
  md:     () => markdown(),
  markdown: () => markdown()
};

export function langFor(ext) {
  return LANGS[String(ext || "").toLowerCase().replace(/^\./, "")] || null;
}

/**
 * Mount an editor.
 * @param {object} opts
 * @param {HTMLElement} opts.parent     the node to fill (must have a height)
 * @param {string} [opts.doc]           initial text
 * @param {string} [opts.ext]           extension or language id
 * @param {boolean} [opts.readOnly]
 * @param {function} [opts.onChange]    (text, isDirty) => void
 * @param {function} [opts.onSave]      called on Ctrl+S
 * @returns {{view, getText, setText, setExt, setReadOnly, focus, destroy}}
 */
export function createEditor(opts = {}) {
  const langConf = new Compartment();
  const roConf   = new Compartment();
  const parent   = opts.parent;
  let lastSaved  = opts.doc || "";
  let changeCb   = opts.onChange || null;
  let saveCb     = opts.onSave || null;

  const langOf = ext => {
    const f = langFor(ext);
    return f ? f() : [];
  };

  const state = EditorState.create({
    doc: opts.doc || "",
    extensions: [
      lineNumbers(),
      highlightActiveLineGutter(),
      highlightSpecialChars(),
      history(),
      foldGutter(),
      drawSelection(),
      dropCursor(),
      EditorState.allowMultipleSelections.of(true),
      indentOnInput(),
      bracketMatching(),
      closeBrackets(),
      autocompletion(),
      rectangularSelection(),
      crosshairCursor(),
      highlightActiveLine(),
      highlightSelectionMatches(),
      syntaxHighlighting(hudHighlight),
      hudTheme,
      EditorView.lineWrapping,
      langConf.of(langOf(opts.ext)),
      roConf.of(opts.readOnly ? EditorState.readOnly.of(true) : []),
      keymap.of([
        {
          key: "Mod-s",
          preventDefault: true,
          run: () => { if (saveCb) saveCb(); return true; }
        },
        ...closeBracketsKeymap,
        ...defaultKeymap,
        ...searchKeymap,
        ...historyKeymap,
        ...foldKeymap,
        ...completionKeymap,
        indentWithTab
      ]),
      EditorView.updateListener.of(u => {
        if (!u.docChanged) return;
        if (opts.readOnly) return;
        if (changeCb) changeCb(u.state.doc.toString(), u.state.doc.toString() !== lastSaved);
      })
    ]
  });

  const view = new EditorView({ state, parent });

  return {
    view,
    getText: () => view.state.doc.toString(),
    setText(text, markClean) {
      view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: text } });
      if (markClean !== false) lastSaved = text;
    },
    markClean(text) { lastSaved = text !== undefined ? text : view.state.doc.toString(); },
    isDirty: () => view.state.doc.toString() !== lastSaved,
    setExt(ext) { view.dispatch({ effects: langConf.reconfigure(langOf(ext)) }); },
    setReadOnly(ro) {
      view.dispatch({ effects: roConf.reconfigure(ro ? EditorState.readOnly.of(true) : []) });
    },
    setHandlers(h) {
      if ("onChange" in h) changeCb = h.onChange;
      if ("onSave"   in h) saveCb   = h.onSave;
    },
    focus() { view.focus(); },
    destroy() { view.destroy(); }
  };
}

// exposed so the stage can label the editor with the bundle's own version
export const VERSION = "cm6-jarvis";
