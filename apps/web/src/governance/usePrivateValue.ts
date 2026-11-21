import { useEffect, useState } from "react";
import type { Channel } from "./useGovernance";

/** Private projections are render-bound to current authority, independently of effects.
 * Unsent input belongs in ordinary local state. Successful retry callbacks may
 * publish only while their current request signal remains live.
 */
export function usePrivateValue<T>(channel: Channel) {
  const [stored, setStored] = useState<{ epoch: number; value: T } | null>(
    null,
  );
  useEffect(() => {
    // Rendering masks old projections first; cleanup then drops their memory.
    setStored((current) =>
      current && current.epoch !== channel.currentPrivateEpoch()
        ? null
        : current,
    );
  }, [channel.privateEpoch]);
  function set(value: T | null, signal?: AbortSignal) {
    if (signal?.aborted) return;
    setStored(
      value === null ? null : { epoch: channel.currentPrivateEpoch(), value },
    );
  }
  const current =
    channel.account !== null && stored?.epoch === channel.privateEpoch
      ? stored.value
      : null;
  return [current, set] as const;
}
