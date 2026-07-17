import type { Metadata } from "next";
import "./globals.css";
import AuthGate from "@/components/AuthGate";
import Shell from "@/components/Shell";

export const metadata: Metadata = {
  title: "M2M Fleet Console",
  description: "Single pane of glass for AATA-governed agent fleets",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html:
          `if(window.matchMedia('(prefers-color-scheme: dark)').matches)document.documentElement.classList.add('sys-dark');`,
        }} />
      </head>
      <body>
        <AuthGate>
          <Shell>{children}</Shell>
        </AuthGate>
      </body>
    </html>
  );
}
