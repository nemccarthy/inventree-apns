import type { SyncResult } from './types';

const NO_API =
  'The Alternative Parts API was not found. Turn on "Enable URL integration" in the InvenTree plugin settings, then restart the server.';

/**
 * Return the data of an API response, checking that it really is a plugin result.
 *
 * With "Enable URL integration" turned off, InvenTree redirects the plugin's
 * URLs to the web interface, so the request "succeeds" with a page of HTML.
 */
export function apiData<T>(response: any, field: string): T {
  const data = response?.data;

  if (!data || typeof data !== 'object' || !(field in data)) {
    throw Object.assign(new Error(NO_API), { apnsNoApi: true });
  }

  return data as T;
}

/** Turn an API error into a message for the user */
export function apiError(err: any, fallback: string): string {
  const status = err?.response?.status;
  const data = err?.response?.data;

  if (err?.apnsNoApi || (status === 404 && typeof data !== 'object')) {
    return NO_API;
  }

  if (status === 403) {
    return 'You do not have permission to do this.';
  }

  if (data && typeof data === 'object') {
    const messages: string[] = [];

    for (const value of Object.values(data)) {
      if (Array.isArray(value)) {
        messages.push(...value.map(String));
      } else if (typeof value === 'string') {
        messages.push(value);
      }
    }

    if (messages.length > 0) {
      return messages.join(' ');
    }
  }

  return `${fallback}${err?.message ? `: ${err.message}` : ''}`;
}

export function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

export function fmtQty(value: number | undefined): string {
  if (value === undefined || value === null) {
    return '';
  }

  return Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) {
    return '';
  }

  const date = new Date(iso);

  if (Number.isNaN(date.getTime())) {
    return '';
  }

  return date.toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  });
}

/** "2 substitutes added, 1 removed" */
export function syncSummary(result: SyncResult | null | undefined): string {
  if (!result) {
    return '';
  }

  const parts: string[] = [];

  if (result.added > 0) {
    parts.push(`${plural(result.added, 'BOM substitute', 'BOM substitutes')} added`);
  }

  if (result.removed > 0) {
    parts.push(`${result.removed} removed`);
  }

  if (result.skipped > 0) {
    parts.push(`${plural(result.skipped, 'locked BOM line', 'locked BOM lines')} left alone`);
  }

  if (result.errors.length > 0) {
    parts.push(`${plural(result.errors.length, 'substitute', 'substitutes')} could not be added (${result.errors[0].error})`);
  }

  return parts.length > 0 ? parts.join(', ') : 'The BOMs were already up to date';
}
