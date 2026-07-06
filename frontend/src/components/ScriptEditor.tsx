"use client";
import Editor, { type OnMount } from "@monaco-editor/react";
import { useEffect, useRef } from "react";
import type * as Monaco from "monaco-editor";
import { useTranslation } from "react-i18next";

export interface LintIssue {
  line: number;
  col: number;
  end_line: number;
  end_col: number;
  message: string;
  severity: "error" | "warning";
}

export interface EditorSelection {
  text: string;
  startLine: number;
  endLine: number;
}

interface Props {
  value: string;
  onChange: (value: string | undefined) => void;
  readOnly?: boolean;
  issues?: LintIssue[];
  language?: string;
  /** Fires with the current non-empty selection (or null when nothing selected). */
  onSelectionChange?: (sel: EditorSelection | null) => void;
}

export default function ScriptEditor({ value, onChange, readOnly = false, issues = [], language = "python", onSelectionChange }: Props) {
  const { t } = useTranslation("scriptEditor");
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null);
  const monacoRef = useRef<typeof Monaco | null>(null);

  const handleMount: OnMount = (editor, monaco) => {
    editorRef.current = editor;
    monacoRef.current = monaco;

    monaco.editor.setTheme("vs-dark");

    editor.updateOptions({
      fontSize: 13,
      fontFamily: "var(--font-mono), 'JetBrains Mono', 'Fira Code', monospace",
      fontLigatures: true,
      lineHeight: 22,
      minimap: { enabled: false },
      scrollBeyondLastLine: false,
      renderWhitespace: "boundary",
      tabSize: 4,
      insertSpaces: true,
      wordWrap: "off",
      smoothScrolling: true,
      cursorBlinking: "smooth",
      bracketPairColorization: { enabled: true },
      guides: { bracketPairs: true, indentation: true },
      padding: { top: 12, bottom: 12 },
    });

    editor.getModel()?.updateOptions({ tabSize: 4, insertSpaces: true });

    if (onSelectionChange) {
      editor.onDidChangeCursorSelection((e) => {
        const model = editor.getModel();
        if (!model || e.selection.isEmpty()) { onSelectionChange(null); return; }
        onSelectionChange({
          text: model.getValueInRange(e.selection),
          startLine: e.selection.startLineNumber,
          endLine: e.selection.endLineNumber,
        });
      });
    }
  };

  // push lint issues into Monaco as markers (red squiggles)
  useEffect(() => {
    const monaco = monacoRef.current;
    const editor = editorRef.current;
    if (!monaco || !editor) return;
    const model = editor.getModel();
    if (!model) return;

    const markers = issues.map((iss) => ({
      severity: iss.severity === "error"
        ? monaco.MarkerSeverity.Error
        : monaco.MarkerSeverity.Warning,
      message: iss.message,
      startLineNumber: iss.line,
      startColumn: iss.col,
      endLineNumber: iss.end_line,
      endColumn: iss.end_col,
    }));
    monaco.editor.setModelMarkers(model, "agentflow-lint", markers);
  }, [issues]);

  return (
    <div className="h-full w-full">
      <Editor
        height="100%"
        language={language}
        value={value}
        onChange={onChange}
        onMount={handleMount}
        theme="vs-dark"
        options={{ readOnly, automaticLayout: true }}
        loading={
          <div className="h-full flex items-center justify-center text-muted-foreground text-sm">
            {t("scriptEditor.loadingEditor")}
          </div>
        }
      />
    </div>
  );
}
