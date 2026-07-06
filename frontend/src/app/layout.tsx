import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { Toaster } from "sonner";
import AuthGate from "@/components/AuthGate";
import { AssistantProvider } from "@/components/assistant/AssistantProvider";
import FloatingAssistant from "@/components/FloatingAssistant";
import { ConfirmDialogProvider } from "@/components/ConfirmDialogProvider";
import I18nProvider from "@/components/I18nProvider";
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
        <I18nProvider>
          <AuthGate>
            <ConfirmDialogProvider>
              <AssistantProvider>
                {children}
                <FloatingAssistant />
              </AssistantProvider>
            </ConfirmDialogProvider>
          </AuthGate>
          {/* bottom-right so toasts never cover the header action buttons
              (Run / Save) which live at the top-right of the script page */}
          <Toaster theme="dark" position="bottom-right" richColors />
        </I18nProvider>
      </body>
    </html>
  );
}
