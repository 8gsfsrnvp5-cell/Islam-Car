"use client";

import { ApiError, api, errorText } from "@islamic-car/shared";
import { useRouter } from "next/navigation";
import { useState } from "react";

export default function LoginPage() {
  const router = useRouter();
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [needCode, setNeedCode] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/api/auth/admin/login", { method: "POST", json: { login, password, totp_code: code || null } });
      router.replace("/");
    } catch (err) {
      if (err instanceof ApiError && err.detail === "totp_required") {
        setNeedCode(true);
        setError(null);
      } else {
        setError(errorText(err));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <div className="login">
        <h1>Islamic Car</h1>
        <p className="muted">Вход для сотрудников</p>
        <form onSubmit={submit}>
          <label className="field"><span>Логин</span>
            <input value={login} onChange={(e) => setLogin(e.target.value)} autoComplete="username" required autoFocus />
          </label>
          <label className="field"><span>Пароль</span>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
          </label>
          {needCode ? (
            <label className="field"><span>Код из приложения-аутентификатора</span>
              <input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" autoComplete="one-time-code" autoFocus required />
            </label>
          ) : null}
          {error ? <div className="form-error">{error}</div> : null}
          <button className="btn btn-primary" disabled={busy}>{busy ? "Проверка…" : "Войти"}</button>
        </form>
      </div>
    </div>
  );
}
