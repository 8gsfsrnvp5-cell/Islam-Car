"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/cars", title: "Каталог" },
  { href: "/order", title: "Под заказ" },
  { href: "/how-it-works", title: "Как это работает" },
];

export function HeaderNav() {
  const pathname = usePathname();
  return (
    <nav className="nav">
      {LINKS.map((l) => (
        <Link key={l.href} href={l.href} className={pathname.startsWith(l.href) ? "active" : ""}>{l.title}</Link>
      ))}
    </nav>
  );
}
