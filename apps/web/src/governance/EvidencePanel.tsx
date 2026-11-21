import { usePrivateValue } from "./usePrivateValue";
import { useEffect, useState } from "react";
import { Field, uuidPattern } from "./Fields";
import { read, utc } from "./api";
import type { Text } from "./messages";
import type { AuditPage } from "./types";
import type { Channel } from "./useGovernance";
import { State } from "./Labels";
export function EvidencePanel({
  channel,
  text,
}: {
  channel: Channel;
  text: Text;
}) {
  const [grant, setGrant] = useState(""),
    [from, setFrom] = useState(""),
    [to, setTo] = useState(""),
    [action, setAction] = useState(""),
    [exportId, setExportId] = useState("");
  const [page, setPage] = usePrivateValue<AuditPage>(channel),
    [cursor, setCursor] = useState<string | null>(null),
    [prepared, setPrepared] = usePrivateValue<string>(channel);
  const [pageSource, setPageSource] = useState<
    { kind: "search" } | { kind: "export"; id: string } | null
  >(null);
  useEffect(() => {
    setPage(null);
    setCursor(null);
    setPrepared(null);
    setPageSource(null);
  }, [channel.privateEpoch]);
  function query(next: string | null = null) {
    return {
      purpose: "audit",
      grant_id: grant,
      from: utc(from),
      to: utc(to),
      ...(action ? { action } : {}),
      limit: 50,
      ...(next ? { cursor: next } : {}),
    };
  }
  function search(next: string | null = null) {
    channel.command(
      {
        path: "/v1/audit/search",
        input: "AuditQuery",
        output: "AuditPage",
        body: query(next),
      },
      (value) => {
        setPage(value);
        setCursor(value.next_cursor);
        setPageSource({ kind: "search" });
      },
    );
  }
  function readExport(id: string, next: string | null = null) {
    const params = new URLSearchParams(
      Object.entries(query(next)).map(([key, value]) => [key, String(value)]),
    );
    void channel.run(async (signal) => {
      const value = await read(
        `/v1/audit/exports/${id}?${params}`,
        "AuditPage",
        signal,
      );
      if (signal.aborted) return;
      setPage(value, signal);
      setCursor(value.next_cursor);
      setPageSource({ kind: "export", id });
    });
  }
  return (
    <section aria-labelledby="evidence-title">
      <h2 id="evidence-title">{text.audit}</h2>
      <p>{text.auditHint}</p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          search();
        }}
        onChange={() => {
          setPage(null);
          setCursor(null);
          setPrepared(null);
          setPageSource(null);
        }}
      >
        <fieldset disabled={channel.disabled}>
          <Field
            id="audit-grant"
            label={text.grantId}
            value={grant}
            onChange={setGrant}
            pattern={uuidPattern}
          />
          <Field
            id="audit-from"
            label={text.from}
            value={from}
            onChange={setFrom}
            type="datetime-local"
          />
          <Field
            id="audit-to"
            label={text.to}
            value={to}
            onChange={setTo}
            type="datetime-local"
          />
          <Field
            id="audit-action"
            label={text.action}
            value={action}
            onChange={setAction}
            required={false}
          />
          <button>{text.queryAudit}</button>
          <button
            type="button"
            disabled={!grant || !from || !to}
            onClick={() =>
              channel.command(
                {
                  path: "/v1/audit/exports",
                  input: "AuditQuery",
                  output: "CommandResult",
                  body: query(),
                },
                (value) => {
                  setPrepared(value.resource_id);
                  setExportId(value.resource_id ?? "");
                },
              )
            }
          >
            {text.export}
          </button>
        </fieldset>
      </form>
      {prepared && (
        <p>
          {text.exportId}: <code>{prepared}</code>
        </p>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          readExport(exportId);
        }}
      >
        <fieldset disabled={channel.disabled}>
          <Field
            id="audit-export"
            label={text.exportId}
            value={exportId}
            onChange={(value) => {
              setExportId(value);
              setPage(null);
              setCursor(null);
              setPageSource(null);
            }}
            pattern={uuidPattern}
          />
          <button disabled={!grant || !from || !to}>{text.readExport}</button>
        </fieldset>
      </form>
      {page && (
        <>
          {page.items.length === 0 ? (
            <p>{text.noRows}</p>
          ) : (
            <ul>
              {page.items.map((item) => (
                <li key={item.id}>
                  <dl>
                    <dt>{text.sequence}</dt>
                    <dd>{item.sequence}</dd>
                    <dt>{text.auditAction}</dt>
                    <dd>{item.action}</dd>
                    <dt>{text.auditDecision}</dt>
                    <dd>
                      <State value={item.decision} text={text} />
                    </dd>
                    <dt>{text.created}</dt>
                    <dd>
                      <time dateTime={item.created_at}>{item.created_at}</time>
                    </dd>
                    <dt>{text.chain}</dt>
                    <dd>
                      <code>{item.hash}</code>
                    </dd>
                  </dl>
                </li>
              ))}
            </ul>
          )}
          {cursor && (
            <button
              disabled={channel.disabled}
              onClick={() =>
                pageSource?.kind === "export"
                  ? readExport(pageSource.id, cursor)
                  : search(cursor)
              }
            >
              {text.next}
            </button>
          )}
        </>
      )}
    </section>
  );
}
