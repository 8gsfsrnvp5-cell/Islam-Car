"use client";

import { type ClientContract } from "@islamic-car/shared";

import { useClientApi } from "@/lib/useClientApi";

type Info = { configured: boolean; payee: string; bank_name: string; bik: string; account: string; corr_account: string; inn: string; purpose_hint: string; support_phone: string };

export default function PaymentInfoPage() {
  const info = useClientApi<Info>("/api/client/payment-info");
  const contracts = useClientApi<ClientContract[]>("/api/client/contracts");
  const i = info.data;
  const active = contracts.data?.filter((c) => c.status === "signed") ?? [];

  return (
    <>
      <h1>Как оплатить</h1>
      <div className="notice info">
        Оплачивайте переводом по реквизитам продавца. Платёж засчитывается после поступления денег на счёт и проверки сотрудником —
        затем остаток в кабинете обновится автоматически. Онлайн-оплата через платёжный сервис появится позже.
      </div>
      {!i ? <p>Загрузка…</p> : !i.configured ? (
        <div className="notice warn">Реквизиты ещё не внесены. Уточните способ оплаты у менеджера{i.support_phone ? ` по телефону ${i.support_phone}` : ""}.</div>
      ) : (
        <div className="panel">
          <dl className="kv">
            <dt>Получатель</dt><dd>{i.payee}</dd>
            {i.inn ? <><dt>ИНН</dt><dd className="mono">{i.inn}</dd></> : null}
            <dt>Банк</dt><dd>{i.bank_name}</dd>
            <dt>БИК</dt><dd className="mono">{i.bik}</dd>
            <dt>Расчётный счёт</dt><dd className="mono">{i.account}</dd>
            {i.corr_account ? <><dt>Корр. счёт</dt><dd className="mono">{i.corr_account}</dd></> : null}
          </dl>
          {active.length ? (
            <>
              <h3 style={{ marginTop: 16 }}>Назначение платежа</h3>
              {active.map((c) => <div key={c.id} className="mono small">{i.purpose_hint.replace("{number}", c.number)}</div>)}
            </>
          ) : null}
        </div>
      )}
      <p className="small muted">Никогда не переводите деньги по реквизитам, присланным с незнакомых номеров или адресов. Актуальные реквизиты — только здесь.</p>
    </>
  );
}
