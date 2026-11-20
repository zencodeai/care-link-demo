import { RequestFailure } from "../trust/api";
import type { ReviewWorkLease } from "../plans/review";

// One actor page has one ordered write boundary. An owner may rotate its own
// cookie for verification/recovery without queueing behind itself.
export class WorkGate {
  private owner: ReviewWorkLease | null = null;
  private pending = 0;
  private releaseRequested = false;
  private waiting: {
    signal: AbortSignal;
    view: () => string;
    resolve: (lease: ReviewWorkLease) => void;
    reject: (error: unknown) => void;
    abort: () => void;
  }[] = [];
  owns(lease: ReviewWorkLease | undefined): boolean {
    return !!lease && this.owner === lease;
  }
  hold(lease: ReviewWorkLease, operation: Promise<unknown>): void {
    if (!this.owns(lease)) throw new RequestFailure("rejected");
    this.pending += 1;
    const settled = () => {
      this.pending -= 1;
      this.finish();
    };
    void operation.then(settled, settled);
  }
  private finish(): void {
    if (!this.releaseRequested || this.pending) return;
    this.owner = null;
    this.advance();
  }
  acquire(signal: AbortSignal, view: () => string): Promise<ReviewWorkLease> {
    if (signal.aborted)
      return Promise.reject(new RequestFailure("unavailable"));
    return new Promise<ReviewWorkLease>((resolve, reject) => {
      const entry = {
        signal,
        view,
        resolve,
        reject,
        abort: () => {
          this.waiting = this.waiting.filter((item) => item !== entry);
          reject(new RequestFailure("unavailable"));
          this.advance();
        },
      };
      this.waiting.push(entry);
      signal.addEventListener("abort", entry.abort, { once: true });
      this.advance();
    });
  }
  private advance(): void {
    if (this.owner) return;
    const next = this.waiting.shift();
    if (!next) return;
    next.signal.removeEventListener("abort", next.abort);
    try {
      if (next.signal.aborted) throw new RequestFailure("unavailable");
      const lease: ReviewWorkLease = {
        token: Symbol("review work"),
        view_id: next.view(),
        release: () => {
          if (this.owner !== lease) return;
          this.releaseRequested = true;
          this.finish();
        },
      };
      this.owner = lease;
      this.pending = 0;
      this.releaseRequested = false;
      next.resolve(lease);
    } catch (error) {
      next.reject(error);
      this.advance();
    }
  }
}
export async function withinSignal<T>(
  promise: Promise<T>,
  signal: AbortSignal,
): Promise<T> {
  if (signal.aborted) throw new RequestFailure("unavailable");
  return new Promise<T>((resolve, reject) => {
    const aborted = () => reject(new RequestFailure("unavailable"));
    signal.addEventListener("abort", aborted, { once: true });
    void promise.then(
      (value) => {
        signal.removeEventListener("abort", aborted);
        if (signal.aborted) aborted();
        else resolve(value);
      },
      (error: unknown) => {
        signal.removeEventListener("abort", aborted);
        reject(
          error instanceof Error ? error : new RequestFailure("unavailable"),
        );
      },
    );
  });
}
