"use client";

import { CAR_STATUS, OWNERSHIP, type StaffCar, formatRub } from "@islamic-car/shared";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useCan } from "@/components/Shell";
import { Badge, Card, Empty, ErrorBox, Loading, PageHead, StatusBadge } from "@/components/ui";
import { useApi } from "@/lib/useApi";

const FILTERS = ["", "draft", "available", "reserved", "sold", "archived"];

export default function CarsPage() {
  const router = useRouter();
  const canWrite = useCan("cars.write");
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (q) params.set("q", q);
  const { data, error, loading } = useApi<StaffCar[]>(`/api/admin/cars?${params}`);

  return (
    <>
      <PageHead title="Реестр автомобилей" subtitle="Автомобили в собственности, в процессе закупки и проданные"
                actions={canWrite ? <Link className="btn btn-primary" href="/cars/new">Добавить автомобиль</Link> : null} />
      <div className="actions" style={{ marginBottom: 12 }}>
        <div className="tabs" style={{ margin: 0 }}>
          {FILTERS.map((s) => (
            <button key={s || "all"} className={status === s ? "active" : ""} onClick={() => setStatus(s)}>{s ? CAR_STATUS[s] : "Все"}</button>
          ))}
        </div>
        <input type="search" placeholder="Марка, модель, VIN" value={q} onChange={(e) => setQ(e.target.value)} style={{ maxWidth: 260 }} />
      </div>
      <ErrorBox error={error} />
      <Card flush>
        {loading && !data ? <Loading /> : !data?.length ? <Empty>Автомобилей нет</Empty> : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th></th><th>Автомобиль</th><th>VIN</th><th>Собственность</th><th>Статус</th><th>Каталог</th>
                  <th className="num">Закупка</th><th className="num">Цена продажи</th></tr>
              </thead>
              <tbody>
                {data.map((c) => (
                  <tr key={c.id} className="clickable" onClick={() => router.push(`/cars/${c.id}`)}>
                    <td>{c.photos[0] ? <img className="thumb" src={c.photos[0].url} alt="" /> : <div className="thumb" />}</td>
                    <td><strong>{c.make} {c.model}</strong><div className="small muted">{c.year} · {c.mileage_km.toLocaleString("ru-RU")} км</div></td>
                    <td className="mono small">{c.vin ?? <span className="muted">не указан</span>}</td>
                    <td><StatusBadge status={c.ownership_status} labels={OWNERSHIP} /></td>
                    <td><StatusBadge status={c.status} labels={CAR_STATUS} /></td>
                    <td>{c.is_published ? <Badge tone="ok">Опубликован</Badge> : <Badge>Скрыт</Badge>}</td>
                    <td className="num">{"purchase_price_kopecks" in c ? formatRub(c.purchase_price_kopecks) : "—"}</td>
                    <td className="num"><strong>{formatRub(c.sale_price_kopecks)}</strong></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
