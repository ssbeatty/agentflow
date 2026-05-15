"use client";
import Editor, { type OnMount } from "@monaco-editor/react";
import { useRef } from "react";

interface Props {
  value: string;
  onChange: (value: string | undefined) => void;
  readOnly?: boolean;
}

export default function ScriptEditor({ value, onChange, readOnly = false }: Props) {
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null);

  const handleMount: OnMount = (editor, monaco) => {
    editorRef.current = editor;

    // Python-friendly editor defaults
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

    // Python: use spaces not tabs
    editor.getModel()?.updateOptions({ tabSize: 4, insertSpaces: true });
  };

  return (
    <div className="h-full w-full">
      <Editor
        height="100%"
        defaultLanguage="python"
        value={value}
        onChange={onChange}
        onMount={handleMount}
        theme="vs-dark"
        options={{
          readOnly,
          automaticLayout: true,
        }}
        loading={
          <div className="h-full flex items-center justify-center text-muted-foreground text-sm">
            Loading editor…
          </div>
        }
      />
    </div>
  );
}
