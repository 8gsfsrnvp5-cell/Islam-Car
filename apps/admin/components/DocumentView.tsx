import type { DocBlock, DocCheck } from "@islamic-car/shared";
import type { ReactNode } from "react";

const MARK = /\[\[ЮРИСТ:\s*([\s\S]+?)\]\]/g;

/** Подсвечивает места, где нужно решение юриста. */
function withMarks(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(MARK)) {
    if (m.index! > last) out.push(text.slice(last, m.index));
    out.push(<mark key={m.index} className="lawyer" title="Требуется решение юриста">⚖ {m[1]}</mark>);
    last = m.index! + m[0].length;
  }
  out.push(text.slice(last));
  return out;
}

export function DocumentPaper({ blocks, watermark }: { blocks: DocBlock[]; watermark?: string }) {
  return (
    <div className="paper">
      {watermark ? <div className="paper-mark">{watermark}</div> : null}
      {blocks.map((b, i) => {
        if (b.type === "h1") return <h2 key={i} className="paper-h1">{b.text}</h2>;
        if (b.type === "h2") return <h3 key={i} className="paper-h2">{b.text}</h3>;
        if (b.type === "p") return <p key={i}>{withMarks(b.text)}</p>;
        if (b.type === "note") return <p key={i} className="paper-note">{withMarks(b.text)}</p>;
        if (b.type === "table") {
          return (
            <table key={i} className="paper-table">
              {b.header ? <thead><tr>{b.header.map((h, j) => <th key={j}>{h}</th>)}</tr></thead> : null}
              <tbody>
                {b.rows.map((r, j) => <tr key={j}>{r.map((c, k) => <td key={k}>{c}</td>)}</tr>)}
                {b.footer ? <tr className="paper-total">{b.footer.map((c, k) => <td key={k}>{c}</td>)}</tr> : null}
              </tbody>
            </table>
          );
        }
        if (b.type !== "signatures") return null;
        return (
          <div key={i} className="paper-sign">
            {b.parties.map((p, j) => (
              <div key={j}>
                <strong>{p.title}</strong>
                <div>{p.name || "—"}</div>
                <div className="muted">_________________ / подпись</div>
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}

const ICON: Record<string, string> = { ok: "✓", info: "i", warning: "!", error: "✕" };
const TONE: Record<string, string> = { ok: "ok", info: "warn", warning: "warn", error: "bad" };

export function DocChecks({ checks }: { checks: DocCheck[] }) {
  return (
    <ul className="checks">
      {checks.map((c, i) => (
        <li key={i}><span className={`mark ${TONE[c.level]}`}>{ICON[c.level]}</span><span className="small">{c.message}</span></li>
      ))}
    </ul>
  );
}
