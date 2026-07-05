"use client";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// Shared chat-flavoured markdown renderer. Used by the chat answer, the
// typewriter, and the agent narrative's intermediate text segments.
export function MarkdownContent({ text }: { text: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        p: ({ children }) => <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>,
        h1: ({ children }) => <h1 className="text-lg font-bold mb-2 mt-3 first:mt-0">{children}</h1>,
        h2: ({ children }) => <h2 className="text-base font-bold mb-2 mt-3 first:mt-0">{children}</h2>,
        h3: ({ children }) => <h3 className="text-sm font-semibold mb-1 mt-2 first:mt-0">{children}</h3>,
        ul: ({ children }) => <ul className="list-disc pl-5 mb-2 space-y-0.5">{children}</ul>,
        ol: ({ children }) => <ol className="list-decimal pl-5 mb-2 space-y-0.5">{children}</ol>,
        li: ({ children }) => <li className="leading-relaxed">{children}</li>,
        // react-markdown v10 no longer reliably passes the old `inline` flag.
        // Style code inline by default; the surrounding <pre> resets fenced
        // blocks below, so `run_python(...)` stays in the sentence instead of
        // becoming its own awkward line.
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        code: ({ className, children, ...props }: any) => (
          <code
            className={`bg-muted px-1 py-0.5 rounded text-[0.85em] font-mono ${className ?? ""}`.trim()}
            {...props}
          >
            {children}
          </code>
        ),
        pre: ({ children }) => (
          <pre className="bg-muted rounded-lg p-3 mb-2 overflow-x-auto text-xs font-mono [&_code]:bg-transparent [&_code]:p-0 [&_code]:rounded-none [&_code]:text-xs">{children}</pre>
        ),
        blockquote: ({ children }) => (
          <blockquote className="border-l-2 border-primary/50 pl-3 italic text-muted-foreground mb-2">{children}</blockquote>
        ),
        a: ({ href, children }) => (
          <a href={href} target="_blank" rel="noopener noreferrer" className="text-primary underline underline-offset-2">{children}</a>
        ),
        strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
        em: ({ children }) => <em className="italic">{children}</em>,
        hr: () => <hr className="border-border my-3" />,
        table: ({ children }) => (
          <div className="overflow-x-auto mb-2 rounded-lg border border-border">
            <table className="border-collapse w-full text-xs">{children}</table>
          </div>
        ),
        th: ({ children }) => <th className="border-b border-border px-2.5 py-1.5 bg-muted/60 font-medium text-left">{children}</th>,
        td: ({ children }) => <td className="border-b border-border/50 px-2.5 py-1.5">{children}</td>,
      }}
    >
      {text}
    </ReactMarkdown>
  );
}
