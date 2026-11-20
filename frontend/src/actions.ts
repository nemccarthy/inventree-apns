import type { InvenTreePluginContext } from '@inventreedb/ui';
import { useCallback, useRef, useState } from 'react';

import { apiError, syncSummary } from './api';
import type { SyncResult } from './types';
import type { LinkChoice } from './ui';

/**
 * The changes which can be made from the part panel and the overview page.
 *
 * 'busy' is the key of the row an action is running for, 'message' what the
 * last action did and 'error' why it failed.
 */
export function useActions(
  context: InvenTreePluginContext,
  slug: string,
  onDone: () => void
) {
  const api = useRef(context.api);
  api.current = context.api;

  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(
    async (key: string, action: () => Promise<string>, fallback: string) => {
      setBusy(key);
      setError(null);
      setMessage(null);

      try {
        setMessage(await action());
        onDone();
      } catch (err) {
        setError(apiError(err, fallback));
      } finally {
        setBusy(null);
      }
    },
    [onDone]
  );

  /** Link two parts; 'forward' means 'other' can replace 'part' */
  const link = useCallback(
    (part: number, other: number, choice: LinkChoice, note?: string) =>
      run(
        `${part}:${other}`,
        async () => {
          const body =
            choice === 'reverse'
              ? { part: other, alternate: part, two_way: false, note: note ?? '' }
              : { part, alternate: other, two_way: choice === 'both', note: note ?? '' };

          const response = await api.current.post(`/plugin/${slug}/links/`, body);
          const sync: SyncResult | null = response?.data?.sync ?? null;

          return sync
            ? `Linked. ${syncSummary(sync)}.`
            : 'Linked. The BOMs are not changed until they are synced.';
        },
        'Could not save the link'
      ),
    [run, slug]
  );

  const unlink = useCallback(
    (part: number, other: number) =>
      run(
        `${part}:${other}`,
        async () => {
          const response = await api.current.delete(`/plugin/${slug}/links/`, {
            data: { part, alternate: other }
          });
          const sync: SyncResult | null = response?.data?.sync ?? null;

          return sync
            ? `Link removed. ${syncSummary(sync)}.`
            : 'Link removed. The BOMs are not changed until they are synced.';
        },
        'Could not remove the link'
      ),
    [run, slug]
  );

  const dismiss = useCallback(
    (part: number, other: number, dismissed: boolean) =>
      run(
        `${part}:${other}`,
        async () => {
          await api.current.post(`/plugin/${slug}/dismiss/`, { part, other, dismissed });

          return dismissed ? 'Hidden from the candidates.' : 'Back among the candidates.';
        },
        'Could not save the change'
      ),
    [run, slug]
  );

  const sync = useCallback(
    (parts?: number[]) =>
      run(
        'sync',
        async () => {
          const response = await api.current.post(
            `/plugin/${slug}/sync/`,
            parts ? { parts } : {}
          );

          return `${syncSummary(response?.data as SyncResult)}.`;
        },
        'Could not update the BOMs'
      ),
    [run, slug]
  );

  return { busy, message, error, link, unlink, dismiss, sync };
}
