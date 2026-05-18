"use client";
import { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { ArtifactEvent } from "@/lib/types";
import MermaidView from "@/components/MermaidView";

interface Props {
  items: ArtifactEvent[];
}

export default function ArtifactsPanel({ items }: Props) {
  if (!items.length) {
    return (
      <div className="h-full flex items-center justify-center text-xs text-muted-foreground">
        <p>Call <code className="font-mono">markdown()</code> / <code className="font-mono">image()</code> / <code className="font-mono">table()</code> / <code className="font-mono">html()</code> / <code className="font-mono">mermaid()</code> from your script to render here.</p>
      </div>
    );
  }
  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-3xl mx-auto px-4 py-4 space-y-5">
        {items.map((a, i) => (
          <ArtifactCard key={i} a={a} />
        ))}
      </div>
    </div>
  );
}

export function ArtifactCard({ a }: { a: ArtifactEvent }) {
  return (
    <div className="rounded-lg border border-border/60 bg-secondary/10 overflow-hidden">
      {(a.title || a.kind) && (
        <div className="flex items-center justify-between px-3 py-1.5 border-b border-border/60 text-[10px] uppercase tracking-wider text-muted-foreground">
          <span className="font-semibold">{a.kind}</span>
          {a.title ? <span className="normal-case font-normal truncate ml-2">{a.title}</span> : null}
        </div>
      )}
      <div className="p-3">
        {a.kind === "markdown" && <MarkdownView content={a.content} />}
        {a.kind === "image" && <ImageView url={a.url} alt={a.alt ?? ""} />}
        {a.kind === "table" && <TableView columns={a.columns} rows={a.rows} />}
        {a.kind === "html" && <HtmlView html={a.html} />}
        {a.kind === "mermaid" && <MermaidView source={a.code} />}
      </div>
    </div>
  );
}

function MarkdownView({ content }: { content: string }) {
  return (
    <div className="prose prose-sm prose-invert max-w-none prose-pre:bg-background prose-pre:border prose-pre:border-border/60">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // Intercept ```mermaid``` fenced blocks and render them as diagrams.
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          code: ({ inline, className, children, ...props }: any) => {
            const match = /language-(\w+)/.exec(className || "");
            const lang = match?.[1];
            if (!inline && lang === "mermaid") {
              const code = String(children).replace(/\n$/, "");
              return <MermaidView source={code} className="my-2 flex justify-center overflow-auto" />;
            }
            return <code className={className} {...props}>{children}</code>;
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

function ImageView({ url, alt }: { url: string; alt: string }) {
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={url} alt={alt} className="max-w-full h-auto rounded border border-border/60" />
  );
}

function TableView({ columns, rows }: { columns: string[]; rows: unknown[][] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="border-b border-border/60 text-left">
            {columns.map(c => (
              <th key={c} className="px-2 py-1.5 font-semibold text-muted-foreground">{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-border/30 last:border-0 hover:bg-secondary/20">
              {r.map((cell, j) => (
                <td key={j} className="px-2 py-1.5 text-foreground font-mono whitespace-pre-wrap break-words">
                  {formatCell(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function formatCell(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function HtmlView({ html }: { html: string }) {
  // sandbox: no scripts, no forms, no same-origin. Visual presentation only.
  const srcDoc = useMemo(() => html, [html]);
  return (
    <iframe
      sandbox=""
      srcDoc={srcDoc}
      className="w-full min-h-[120px] bg-white rounded border border-border/60"
      style={{ height: "auto" }}
    />
  );
}
