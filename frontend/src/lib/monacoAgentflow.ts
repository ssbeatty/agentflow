/**
 * Registers in-editor code hints for the built-in `agentflow` SDK on Monaco's
 * `python` language: a completion provider (so `agentflow.` / bare names / an
 * `import` line suggest the SDK functions with signatures + docs) and a hover
 * provider (docs on hovering a known SDK symbol), plus a few `af:*` snippets.
 *
 * Monaco is a singleton shared across every editor instance, and language
 * providers are global to the language — so registration is guarded to run once
 * per Monaco instance (re-mounting the editor must not stack duplicate
 * providers). The SDK catalog lives in `agentflowApi.ts`.
 */
import type * as Monaco from "monaco-editor";
import { AGENTFLOW_API, AGENTFLOW_SNIPPETS, type AgentflowSymbol } from "./agentflowApi";

const registered = new WeakSet<typeof Monaco>();

export function registerAgentflowLanguageFeatures(monaco: typeof Monaco): void {
  if (registered.has(monaco)) return;
  registered.add(monaco);

  const K = monaco.languages.CompletionItemKind;
  const SNIPPET = monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet;

  const kindFor = (sym: AgentflowSymbol): Monaco.languages.CompletionItemKind =>
    sym.kind === "class" ? K.Class : sym.kind === "variable" ? K.Variable : K.Function;

  // `${1:city}` → `city`, `${2}` → `` — for a clean code preview in the docs card.
  const previewOf = (body: string) => body.replace(/\$\{\d+:?([^}]*)\}/g, "$1");

  const apiSuggestions = (range: Monaco.IRange, importCtx: boolean): Monaco.languages.CompletionItem[] =>
    AGENTFLOW_API.map((sym) => {
      const asSnippet = !importCtx && !!sym.insert;
      return {
        label: sym.name,
        kind: kindFor(sym),
        detail: `${sym.signature}  ·  agentflow`,
        documentation: { value: sym.doc },
        insertText: importCtx ? sym.name : (sym.insert ?? sym.name),
        insertTextRules: asSnippet ? SNIPPET : undefined,
        range,
        sortText: `0_${sym.group}_${sym.name}`,
      };
    });

  const snippetSuggestions = (range: Monaco.IRange): Monaco.languages.CompletionItem[] =>
    AGENTFLOW_SNIPPETS.map((sn) => ({
      label: sn.label,
      kind: K.Snippet,
      detail: sn.detail,
      documentation: { value: `${sn.doc}\n\n\`\`\`python\n${previewOf(sn.body)}\n\`\`\`` },
      insertText: sn.body,
      insertTextRules: SNIPPET,
      filterText: sn.label,
      range,
      sortText: `1_${sn.label}`,
    }));

  monaco.languages.registerCompletionItemProvider("python", {
    triggerCharacters: ["."],
    provideCompletionItems(model, position) {
      const lineToCursor = model.getValueInRange({
        startLineNumber: position.lineNumber,
        startColumn: 1,
        endLineNumber: position.lineNumber,
        endColumn: position.column,
      });
      const word = model.getWordUntilPosition(position);
      const range: Monaco.IRange = {
        startLineNumber: position.lineNumber,
        endLineNumber: position.lineNumber,
        startColumn: word.startColumn,
        endColumn: word.endColumn,
      };

      // Resolve the module alias(es): `agentflow`, plus `import agentflow as X`.
      const doc = model.getValue();
      const aliases = ["agentflow"];
      const aliasMatch = doc.match(/import\s+agentflow\s+as\s+(\w+)/);
      if (aliasMatch) aliases.push(aliasMatch[1]);

      // Member access `<name>.<partial>`: only offer SDK symbols after an
      // agentflow module/alias; any OTHER `foo.` returns nothing so we don't
      // pollute unrelated attribute completion.
      const memberMatch = lineToCursor.match(/([A-Za-z_]\w*)\s*\.\s*\w*$/);
      if (memberMatch) {
        if (!aliases.includes(memberMatch[1])) return { suggestions: [] };
        return { suggestions: apiSuggestions(range, false) };
      }

      // `from agentflow import a, b<cursor>` — insert bare names (no call snippet).
      if (/from\s+agentflow\s+import\s+[\w,\s]*$/.test(lineToCursor)) {
        return { suggestions: apiSuggestions(range, true) };
      }

      // Bare identifier: SDK symbols (Monaco filters by the typed prefix) + af:* snippets.
      return { suggestions: [...apiSuggestions(range, false), ...snippetSuggestions(range)] };
    },
  });

  monaco.languages.registerHoverProvider("python", {
    provideHover(model, position) {
      // Only when the file references agentflow, so we don't hover a user's own
      // like-named function (e.g. their own `log`).
      if (!/\bagentflow\b/.test(model.getValue())) return null;
      const w = model.getWordAtPosition(position);
      if (!w) return null;
      const sym = AGENTFLOW_API.find((s) => s.name === w.word);
      if (!sym) return null;
      return {
        range: {
          startLineNumber: position.lineNumber,
          endLineNumber: position.lineNumber,
          startColumn: w.startColumn,
          endColumn: w.endColumn,
        },
        contents: [{ value: "```python\n" + sym.signature + "\n```" }, { value: sym.doc }],
      };
    },
  });
}
