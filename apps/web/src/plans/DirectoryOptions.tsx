import { useState } from "react";
import type { DirectoryEntry, Locale } from "./api";
import { stateLabels, textFor } from "./messages";
import type { PlansChannel } from "./usePlans";
export function optionAvailability(
  entry: DirectoryEntry,
): "available" | "unavailableOption" | "unknownOption" {
  if (
    entry.state === "suspended" ||
    entry.facts.operating_state === "temporary_closure" ||
    entry.facts.operating_state === "regional_outage"
  )
    return "unavailableOption";
  if (
    entry.state !== "verified" ||
    Date.parse(entry.expires_at) <= Date.now() ||
    entry.facts.operating_state !== "normal_operations"
  )
    return "unknownOption";
  if (entry.facts.availability === "available_fixture") return "available";
  return entry.facts.availability === "unavailable"
    ? "unavailableOption"
    : "unknownOption";
}
export function DirectoryOptions({
  channel,
  locale,
}: {
  channel: PlansChannel;
  locale: Locale;
}) {
  const text = textFor(locale);
  const [jurisdiction, setJurisdiction] = useState("CA-XX");
  const [need, setNeed] = useState("client_support");
  const entries = channel.directory?.items;
  const disabled = channel.busy || !!channel.pending;
  function search(cursor?: string) {
    channel.command("/v1/directory/search", "DirectoryQuery", "DirectoryPage", {
      jurisdiction,
      locale,
      need,
      limit: 50,
      ...(cursor ? { cursor } : {}),
    });
  }
  return (
    <section aria-labelledby="directory-title">
      <h3 id="directory-title">{text.options}</h3>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          search();
        }}
      >
        <label htmlFor="directory-jurisdiction">{text.jurisdiction}</label>
        <select
          id="directory-jurisdiction"
          value={jurisdiction}
          onChange={(event) => setJurisdiction(event.target.value)}
        >
          <option>CA-XX</option>
          <option>CA-YY</option>
        </select>
        <label htmlFor="directory-need">{text.need}</label>
        <select
          id="directory-need"
          value={need}
          onChange={(event) => setNeed(event.target.value)}
        >
          <option value="client_support">{text.clientSupport}</option>
          <option value="carer_support">{text.carerSupport}</option>
          <option value="navigation">{text.navigation}</option>
          <option value="interpretation">{text.interpretation}</option>
        </select>
        <button type="submit" disabled={disabled || !channel.account}>
          {text.search}
        </button>
      </form>
      {entries?.length === 0 && <p>{text.noOptions}</p>}
      {entries && (
        <ul>
          {entries.map((entry) => (
            <li key={entry.id}>
              <h4>{entry.facts.name}</h4>
              <p>{stateLabels[locale][entry.facts.operating_state]}</p>
              <p>
                {text.admission}:{" "}
                {entry.state === "verified"
                  ? text.verified
                  : entry.state === "suspended"
                    ? text.suspended
                    : entry.state === "quarantined"
                      ? text.quarantined
                      : text.stale}
              </p>
              <p>
                {text.availability}:{" "}
                <strong>{text[optionAvailability(entry)]}</strong>
              </p>
              <p>
                {text.hours}: {entry.facts.hours_description}
              </p>
              <p>
                {text.police}:{" "}
                {entry.facts.police_involvement === "independent_fixture"
                  ? text.independent_fixture
                  : entry.facts.police_involvement === "third_party_possible"
                    ? text.third_party_possible
                    : text.policeUnknown}
              </p>
              {entry.facts.qualifications.map((qualification, index) => (
                <p key={index}>{qualification}</p>
              ))}
              <p>{text.noEta}</p>
              <p>
                {entry.facts.alternative_service_id
                  ? `${text.alternative}: ${entries.find((item) => item.id === entry.facts.alternative_service_id)?.facts.name ?? entry.facts.alternative_service_id}`
                  : text.noAlternative}
              </p>
              <details>
                <summary>{text.provenance}</summary>
                <p>
                  {text.revision}: {entry.revision}
                </p>
                <p>
                  {text.verification}:{" "}
                  <time dateTime={entry.verified_at}>{entry.verified_at}</time>
                </p>
                <p>
                  {text.expires}:{" "}
                  <time dateTime={entry.expires_at}>{entry.expires_at}</time>
                </p>
                <ul>
                  {entry.sources.map((source) => (
                    <li key={source.id + source.revision}>
                      {source.kind}: <code>{source.id}</code> · {text.revision}{" "}
                      {source.revision} · {source.verification} ·{" "}
                      <time dateTime={source.observed_at}>
                        {source.observed_at}
                      </time>
                      <p>
                        {text.digest}: <code>{source.digest}</code>
                      </p>
                    </li>
                  ))}
                </ul>
              </details>
            </li>
          ))}
        </ul>
      )}
      {channel.directory?.next_cursor && (
        <button
          type="button"
          disabled={disabled}
          onClick={() => search(channel.directory?.next_cursor ?? undefined)}
        >
          {text.next}
        </button>
      )}
    </section>
  );
}
