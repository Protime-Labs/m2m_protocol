"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { supabase } from "@/lib/supabase";

const NAV = [
  { href: "/", label: "Dashboard", icon: "▦" },
  { href: "/agents", label: "Agents", icon: "🤖" },
  { href: "/detections", label: "Detections", icon: "⚠" },
  { href: "/evidence", label: "Evidence", icon: "⛓" },
  { href: "/reports", label: "Reports", icon: "📊" },
];

export default function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const toggleTheme = () => {
    const el = document.documentElement;
    const cur = el.getAttribute("data-theme");
    const sysDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    el.setAttribute("data-theme", (cur ?? (sysDark ? "dark" : "light")) === "dark" ? "light" : "dark");
  };

  return (
    <div className="shell">
      <nav className="nav">
        <div className="brand">
          <div className="logo">M2</div>
          <div><b>M2M Fleet Console</b><small>AATA trust overlay</small></div>
        </div>
        <div className="sec">Monitor</div>
        {NAV.map((n) => {
          const on = n.href === "/" ? path === "/" : path.startsWith(n.href);
          return (
            <Link key={n.href} href={n.href} className={`item${on ? " on" : ""}`}>
              <span aria-hidden style={{ width: 18, textAlign: "center" }}>{n.icon}</span>
              {n.label}
            </Link>
          );
        })}
        <div className="sec">About</div>
        <div style={{ padding: "4px 12px", fontSize: 11.5, color: "var(--ink-mut)" }}>
          Read-only operational mirror of estate evidence. Enforcement stays estate-side,
          fail-closed. Intune-style surface; assume-breach core.
        </div>
      </nav>
      <div className="main">
        <div className="topbar">
          <span className="crumb">Protime Labs · fleet management</span>
          <div className="spacer" />
          <button className="btn ghost" onClick={toggleTheme}>Theme</button>
          <button className="btn ghost" onClick={() => supabase().auth.signOut()}>Sign out</button>
        </div>
        <div className="content">{children}</div>
      </div>
    </div>
  );
}
