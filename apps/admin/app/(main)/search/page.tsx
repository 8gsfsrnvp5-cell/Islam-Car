"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { Card, Empty, ErrorBox, Loading, PageHead } from "@/components/ui";
import { useApi } from "@/lib/useApi";

type Hit = { id: string; title: string; subtitle: string };
type Results = { clients: Hit[]; cars: Hit[]; contracts: Hit[]; applications: Hit[] };

const GROUPS: { key: keyof Results; title: string; href: string }[] = [
  { key: "contracts", title: "Договоры", href: "/contracts/" },
  { key: "clients", title: "Клиенты", href: "/clients/" },
  { key: "cars", title: "Автомобили", href: "/cars/" },
  { key: "applications", title: "Заявки", href: "/applications/" },
];

function SearchResults() {
  const q = useSearchParams().get("q") ?? "";
  const { data, error, loading } = useApi<Results>(q ? `/api/admin/search?q=${encodeURIComponent(q)}` : null);
  const total = data ? GROUPS.reduce((s, g) => s + data[g.key].length, 0) : 0;

  return (
    <>
      <PageHead title={`Поиск: «${q}»`} subtitle="ФИО, телефон, VIN, номер договора, автомобиль" />
      <ErrorBox error={error} />
      {loading ? <Loading /> : !data || total === 0 ? <Card><Empty>Ничего не найдено</Empty></Card> : (
        <div className="grid grid-2">
          {GROUPS.filter((g) => data[g.key].length).map((g) => (
            <Card key={g.key} title={g.title} flush>
              <table><tbody>
                {data[g.key].map((h) => (
                  <tr key={h.id}><td><Link href={`${g.href}${h.id}`}>{h.title}</Link><div className="small muted">{h.subtitle}</div></td></tr>
                ))}
              </tbody></table>
            </Card>
          ))}
        </div>
      )}
    </>
  );
}

export default function SearchPage() {
  return <Suspense fallback={<Loading />}><SearchResults /></Suspense>;
}
