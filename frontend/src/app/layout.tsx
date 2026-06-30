import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { Toaster } from "sonner";
import AuthGate from "@/components/AuthGate";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono" });

export const metadata: Metadata = {
  title: "AgentFlow",
  description: "LangGraph Agent IDE",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh" className="dark">
      <body className={`${inter.variable} ${mono.variable} font-sans antialiased min-h-screen`}>
        <AuthGate>{children}</AuthGate>
        <Toaster theme="dark" position="bottom-right" richColors />
      </body>
    </html>
  );
}
