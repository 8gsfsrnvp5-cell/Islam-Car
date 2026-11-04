"use client";

import { INSURANCE_KIND, PLEDGE_STATUS, type InsurancePolicy, type Pledge, formatDate } from "@islamic-car/shared";
import Link from "next/link";

import { Badge, Card, Empty, ErrorBox, Loading, Notice, PageHead, StatusBadge } from "@/components/ui";
import { useApi } from "@/lib/useApi";

function daysLeft(iso: string): number {
  return Math.ceil((new Date(iso).getTime() - Date.now()) / 86_400_000);
}

export default function CollateralPage() {
  const pledges = useApi<Pledge[]>("/api/admin/pledges");
  const insurance = useApi<InsurancePolicy[]>("/api/admin/insurance");

  return (
    <>
      <PageHead title="Залоги и страхование" subtitle="Внутренний реестр обеспечения и полисов по договорам" />
      <Notice tone="info">
        Статусы отражают реальные действия сотрудников. «Зарегистрирован» ставится только с номером уведомления из реестра
        уведомлений о залоге движимого имущества. Система не отправляет документы нотариусу и не отмечает нотариальные действия сама.
        Карточка создаётся при подписании договора; после полной оплаты статус меняется на «Нужно прекратить» и появляется задача.
      </Notice>
      <Card title="Реестр залогов" flush>
        <ErrorBox error={pledges.error} />
        {pledges.loading && !pledges.data ? <Loading /> : !pledges.data?.length ? <Empty>Залогов нет — карточки появятся после подписания договоров</Empty> : (
          <table>
            <thead><tr><th>Договор</th><th>Залогодатель</th><th>Автомобиль</th><th>Уведомление</th><th>Статус</th></tr></thead>
            <tbody>
              {pledges.data.map((p) => (
                <tr key={p.id}>
                  <td><Link href={`/contracts/${p.contract_id}`}>№ {p.contract_number}</Link></td>
                  <td>{p.client}</td>
                  <td>{p.car}<div className="small muted mono">{p.vin}</div></td>
                  <td className="small">{p.registry_number ? `${p.registry_number} от ${formatDate(p.registered_on)}` : "—"}</td>
                  <td><StatusBadge status={p.status} labels={PLEDGE_STATUS} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      <Card title="Полисы страхования" flush>
        <ErrorBox error={insurance.error} />
        {!insurance.data?.length ? <Empty>Полисы не внесены. Добавляются в карточке договора.</Empty> : (
          <table>
            <thead><tr><th>Полис</th><th>Автомобиль</th><th>Страховщик</th><th>Действует до</th><th></th></tr></thead>
            <tbody>
              {insurance.data.map((i) => {
                const left = daysLeft(i.valid_to);
                return (
                  <tr key={i.id}>
                    <td>{INSURANCE_KIND[i.kind]} № {i.number}</td>
                    <td>{i.car}</td>
                    <td>{i.insurer || "—"}</td>
                    <td>{formatDate(i.valid_to)}</td>
                    <td>{left < 0 ? <Badge tone="danger">истёк</Badge> : left <= 30 ? <Badge tone="warn">осталось {left} дн.</Badge> : <Badge tone="ok">действует</Badge>}
                      {i.required_by_contract ? <> <Badge tone="info">по договору</Badge></> : null}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}
