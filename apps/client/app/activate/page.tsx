"use client";

import { api, errorText } from "@islamic-car/shared";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

function ActivateForm() {
  const token = useSearchParams().get("token") ?? "";
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (password !== repeat) { setError("Пароли не совпадают"); return; }
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ login: string }>("/api/auth/client/activate", { method: "POST", json: { token, password } });
      setDone(r.login);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  if (!token) return <div className="notice danger">Ссылка неполная. Попросите менеджера выдать новую.</div>;
  if (done) {
    return (
      <div className="notice ok">
        <strong>Пароль установлен</strong>
        Ваш логин — номер телефона {done}. <Link href="/login">Войти в личный кабинет</Link>
      </div>
    );
  }
  return (
    <form className="form" onSubmit={submit}>
      <label className="field"><span>Новый пароль</span><input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" minLength={10} required /><small>Не короче 10 символов</small></label>
      <label className="field"><span>Повторите пароль</span><input type="password" value={repeat} onChange={(e) => setRepeat(e.target.value)} autoComplete="new-password" required /></label>
      {error ? <div className="form-error">{error}</div> : null}
      <button className="btn btn-primary btn-block" disabled={busy}>Установить пароль</button>
    </form>
  );
}

export default function ActivatePage() {
  return (
    <div className="container auth">
      <div className="panel">
        <h1>Доступ в личный кабинет</h1>
        <p className="muted small">Ссылка одноразовая. Придумайте пароль, который вы не используете на других сайтах.</p>
        <Suspense fallback={<p>Загрузка…</p>}><ActivateForm /></Suspense>
      </div>
    </div>
  );
}
