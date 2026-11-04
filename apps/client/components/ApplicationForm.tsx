"use client";

import { api, errorText, formatRub, pluralMonths, rublesToKopecks } from "@islamic-car/shared";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

type Props =
  | { kind: "catalog"; carId: string; price: number; minDown: number | null; maxTerm: number | null }
  | { kind: "custom_order" };

/** Предварительный расчёт: цена без процентов делится на равные платежи (как в договоре — округление до рубля). */
function monthly(price: number, down: number, term: number): number {
  const per = Math.floor((price - down) / term);
  return per - (per % 100);
}

export function ApplicationForm(props: Props) {
  const router = useRouter();
  const isCatalog = props.kind === "catalog";
  const maxTerm = isCatalog && props.maxTerm ? props.maxTerm : 36;
  const defaultDown = isCatalog ? (props.minDown ?? Math.round(props.price * 0.3 / 10000) * 10000) : null;

  const [down, setDown] = useState(defaultDown !== null ? String(Math.round(defaultDown / 100)) : "");
  const [term, setTerm] = useState(String(Math.min(12, maxTerm)));
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [comment, setComment] = useState("");
  const [wanted, setWanted] = useState({ make: "", model: "", year: "", trim: "", budget: "" });
  const [consent, setConsent] = useState(false);
  const [website, setWebsite] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const downK = rublesToKopecks(down);
  const termN = Number(term);
  const calc = isCatalog && downK !== null && !Number.isNaN(downK) && downK < props.price && termN > 0
    ? monthly(props.price, downK, termN) : null;
  const belowMin = isCatalog && props.minDown !== null && downK !== null && downK < props.minDown;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const budget = rublesToKopecks(wanted.budget);
    if ((downK !== null && Number.isNaN(downK)) || (budget !== null && Number.isNaN(budget))) {
      setError("Суммы указываются в рублях, например 600 000");
      return;
    }
    setBusy(true);
    try {
      const r = await api<{ public_token: string }>("/api/public/applications", {
        method: "POST",
        json: {
          kind: props.kind, name, phone, comment, website,
          car_id: isCatalog ? props.carId : null,
          desired_down_payment_kopecks: downK, desired_term_months: termN || null,
          wanted_make: wanted.make, wanted_model: wanted.model, wanted_year: wanted.year ? Number(wanted.year) : null,
          wanted_trim: wanted.trim, max_budget_kopecks: budget, consent_personal_data: consent,
        },
      });
      router.push(`/status/${r.public_token}?new=1`);
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }

  return (
    <form className="form" onSubmit={submit}>
      {!isCatalog ? (
        <>
          <div className="form-row">
            <label className="field"><span>Марка</span><input value={wanted.make} onChange={(e) => setWanted({ ...wanted, make: e.target.value })} required /></label>
            <label className="field"><span>Модель</span><input value={wanted.model} onChange={(e) => setWanted({ ...wanted, model: e.target.value })} required /></label>
          </div>
          <div className="form-row">
            <label className="field"><span>Год выпуска (не старше)</span><input type="number" min={1980} max={2100} value={wanted.year} onChange={(e) => setWanted({ ...wanted, year: e.target.value })} /></label>
            <label className="field"><span>Максимальный бюджет, ₽</span><input value={wanted.budget} onChange={(e) => setWanted({ ...wanted, budget: e.target.value })} inputMode="numeric" /></label>
          </div>
          <label className="field"><span>Желаемая комплектация</span><textarea value={wanted.trim} onChange={(e) => setWanted({ ...wanted, trim: e.target.value })} placeholder="Коробка, цвет, опции — что важно" /></label>
        </>
      ) : null}

      <div className="form-row">
        <label className="field"><span>Первоначальный взнос, ₽</span>
          <input value={down} onChange={(e) => setDown(e.target.value)} inputMode="numeric" />
          {isCatalog && props.minDown ? <small>Минимум {formatRub(props.minDown)}</small> : null}
        </label>
        <label className="field"><span>Срок выплаты, мес.</span>
          <input type="number" min={1} max={maxTerm} value={term} onChange={(e) => setTerm(e.target.value)} />
          {isCatalog && props.maxTerm ? <small>До {pluralMonths(props.maxTerm)}</small> : null}
        </label>
      </div>

      {isCatalog ? (
        <div className="calc-result">
          {calc !== null ? <>Ежемесячный платёж около <strong>{formatRub(calc)}</strong> × {pluralMonths(termN)}</> : "Укажите взнос меньше цены и срок"}
          <div className="small muted">Предварительный расчёт. Окончательные условия — в договоре. Цена не увеличивается из-за рассрочки.</div>
          {belowMin ? <div className="small form-error">Взнос ниже минимального для этого автомобиля — менеджер обсудит условия.</div> : null}
        </div>
      ) : null}

      <label className="field"><span>Ваше имя</span><input value={name} onChange={(e) => setName(e.target.value)} required minLength={2} autoComplete="given-name" /></label>
      <label className="field"><span>Телефон</span><input value={phone} onChange={(e) => setPhone(e.target.value)} required type="tel" autoComplete="tel" placeholder="+7 900 000-00-00" /></label>
      <label className="field"><span>Комментарий</span><textarea value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Удобное время для звонка, вопросы" /></label>
      <div className="hp" aria-hidden="true"><input tabIndex={-1} autoComplete="off" value={website} onChange={(e) => setWebsite(e.target.value)} name="website" /></div>
      <label className="check">
        <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} required />
        <span>Согласен на обработку имени и телефона для ответа на заявку. <Link href="/privacy" target="_blank">Подробнее</Link></span>
      </label>
      {error ? <div className="form-error">{error}</div> : null}
      <button className="btn btn-primary btn-block" disabled={busy || !consent}>{busy ? "Отправка…" : "Отправить заявку"}</button>
      <p className="small muted">Паспортные данные сейчас не нужны. Менеджер свяжется с вами и расскажет о следующих шагах.</p>
    </form>
  );
}
