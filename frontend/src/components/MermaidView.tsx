"use client";
import { useEffect, useRef, useState } from "react";
import mermaid from "mermaid";
import { AlertCircle } from "lucide-react";

// Initialize mermaid once across the app — safe to call multiple times.
let _initialized = false;
function ensureInit() {
  if (_initialized) return;
  _initialized = true;
  mermaid.initialize({
    startOnLoad: false,
    theme: "base",
    securityLevel: "loose",
    flowchart: { htmlLabels: true, curve: "basis" },
    themeVariables: {
      background: "transparent",
      primaryColor: "#1e293b",
      primaryTextColor: "#e5e7eb",
      primaryBorderColor: "#475569",
      secondaryColor: "#334155",
      tertiaryColor: "#0f172a",
      lineColor: "#94a3b8",
      textColor: "#e5e7eb",
      nodeBorder: "#475569",
      clusterBkg: "#1e293b",
      clusterBorder: "#475569",
      edgeLabelBackground: "#0f172a",
      labelTextColor: "#e5e7eb",
      titleColor: "#e5e7eb",
      mainBkg: "#1e293b",
      nodeTextColor: "#e5e7eb",
    },
  });
}

let _renderCounter = 0;

export default function MermaidView({ source, className }: { source: string; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    ensureInit();
    if (!ref.current || !source) return;
    const id = `mmd-${++_renderCounter}`;
    setError(null);
    mermaid.render(id, source)
      .then(({ svg }) => {
        if (ref.current) ref.current.innerHTML = svg;
      })
      .catch((e: Error) => setError(e.message));
  }, [source]);

  if (error) {
    return (
      <div className="p-3 text-xs text-amber-400">
        <AlertCircle className="inline h-3 w-3 mr-1" />
        Mermaid render failed: {error}
        <details className="mt-1">
          <summary className="cursor-pointer text-muted-foreground">source</summary>
          <pre className="mt-1 text-[10px] text-muted-foreground whitespace-pre-wrap">{source}</pre>
        </details>
      </div>
    );
  }
  return <div ref={ref} className={className ?? "p-2 flex justify-center overflow-auto"} />;
}
