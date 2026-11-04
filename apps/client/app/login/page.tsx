"use client";

import { api, errorText } from "@islamic-car/shared";
import { useRouter } from "next/navigation";
import { useState } from "react";

export default function LoginPage() {
  const router = useRouter();
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/api/auth/client/login", { method: "POST", json: { login, password } });
      router.replace("/cabinet");
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }

  return (
    <div className="container auth">
      <div className="panel">
        <h1>Вход в личный кабинет</h1>
        <p className="muted small">Доступ выдаёт менеджер после оформления договора и проверки личности.</p>
        <form className="form" onSubmit={submit}>
          <label className="field"><span>Телефон</span><input value={login} onChange={(e) => setLogin(e.target.value)} type="tel" autoComplete="username" required /></label>
          <label className="field"><span>Пароль</span><input value={password} onChange={(e) => setPassword(e.target.value)} type="password" autoComplete="current-password" required /></label>
          {error ? <div className="form-error">{error}</div> : null}
          <button className="btn btn-primary btn-block" disabled={busy}>{busy ? "Вход…" : "Войти"}</button>
        </form>
      </div>
    </div>
  );
}
