import type { InvenTreePluginContext } from '@inventreedb/ui';
import { Alert, Badge, Button, Checkbox, Group, Stack, Table, Text } from '@mantine/core';
import { IconDatabaseImport, IconSearch } from '@tabler/icons-react';
import { useCallback, useEffect, useRef, useState } from 'react';

import { apiData, apiError, plural } from './api';
import type { EnrichResult, Proposal, Settings } from './types';

const SOURCE: Record<string, string> = {
  digikey: 'DigiKey',
  lcsc: 'LCSC',
  description: 'Name and description'
};

const STATUS: Record<string, string> = {
  found: 'teal',
  none: 'gray',
  off: 'gray',
  error: 'red'
};

function canAdd(proposal: Proposal): boolean {
  return (proposal.action === 'add' || proposal.action === 'create') && proposal.value !== null;
}

/** Which sources are set up, as a sentence */
export function sourcesNote(settings: Settings): string {
  const off: string[] = [];

  if (!settings.digikey) {
    off.push('DigiKey (no client id and secret in the plugin settings)');
  }

  if (!settings.lcsc) {
    off.push('LCSC (turned off in the plugin settings)');
  }

  return off.length > 0 ? `Not set up: ${off.join(', ')}.` : '';
}

/** Find parameter values for a part, and add the ones which are ticked */
export function EnrichBox({
  context,
  slug,
  part,
  settings,
  onAdded,
  autoStart
}: Readonly<{
  context: InvenTreePluginContext;
  slug: string;
  part: number;
  settings: Settings;
  onAdded: () => void;
  autoStart?: boolean;
}>) {
  const api = useRef(context.api);
  api.current = context.api;

  const [result, setResult] = useState<EnrichResult | null>(null);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const find = useCallback(() => {
    setLoading(true);
    setError(null);
    setDone(null);

    api.current
      .post(`/plugin/${slug}/enrich/`, { part })
      .then((response) => {
        const data = apiData<EnrichResult>(response, 'proposals');
        setResult(data);
        setChosen(new Set(data.proposals.filter(canAdd).map((item) => item.template_name)));
      })
      .catch((err) => setError(apiError(err, 'Could not look the part up')))
      .finally(() => setLoading(false));
  }, [part, slug]);

  useEffect(() => {
    setResult(null);
    setDone(null);
    setError(null);

    if (autoStart) {
      find();
    }
  }, [part, autoStart, find]);

  const add = useCallback(() => {
    setSaving(true);
    setError(null);

    api.current
      .post(`/plugin/${slug}/enrich/`, { part, apply: true, only: Array.from(chosen) })
      .then((response) => {
        const data = apiData<EnrichResult>(response, 'proposals');
        const added = data.applied?.added.length ?? 0;
        const failed = data.applied?.errors ?? [];

        setResult(data);
        setChosen(new Set());
        setDone(
          `${plural(added, 'parameter', 'parameters')} added.` +
            (failed.length > 0
              ? ` ${failed.map((item) => `${item.name}: ${item.error}`).join(' ')}`
              : '')
        );

        if (added > 0) {
          onAdded();
        }
      })
      .catch((err) => setError(apiError(err, 'Could not add the parameters')))
      .finally(() => setSaving(false));
  }, [part, slug, chosen, onAdded]);

  const toggle = (name: string) => {
    setChosen((current) => {
      const next = new Set(current);

      if (next.has(name)) {
        next.delete(name);
      } else {
        next.add(name);
      }

      return next;
    });
  };

  if (!result) {
    return (
      <Stack gap='xs'>
        {error && <Alert color='red'>{error}</Alert>}
        <Group gap='sm'>
          <Button
            size='xs'
            variant='default'
            leftSection={<IconSearch size={14} />}
            loading={loading}
            onClick={find}
          >
            Find parameters
          </Button>
          <Text size='xs' c='dimmed'>
            Looks the part up at the suppliers which are set up, and reads its name and
            description. Nothing is changed until you choose what to add.
          </Text>
        </Group>
      </Stack>
    );
  }

  const addable = result.proposals.filter(canAdd);

  return (
    <Stack gap='xs'>
      {error && <Alert color='red'>{error}</Alert>}
      {done && <Alert color='teal'>{done}</Alert>}
      <Stack gap={2}>
        {result.report.map((item) => (
          <Group key={item.source} gap={6} wrap='nowrap' align='flex-start'>
            <Badge size='xs' color={STATUS[item.status]} variant='light' style={{ flexShrink: 0 }}>
              {SOURCE[item.source] ?? item.source}
            </Badge>
            <Text size='xs' c={item.status === 'error' ? 'red' : 'dimmed'}>
              {item.detail}
            </Text>
          </Group>
        ))}
      </Stack>
      {result.proposals.length === 0 ? (
        <Text size='sm' c='dimmed'>
          Nothing was found for this part. {sourcesNote(settings)}
        </Text>
      ) : (
        <Table verticalSpacing={4} fz='sm'>
          <Table.Thead>
            <Table.Tr>
              <Table.Th w={32} />
              <Table.Th>Parameter</Table.Th>
              <Table.Th>Value</Table.Th>
              <Table.Th>From</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {result.proposals.map((proposal) => (
              <Table.Tr key={`${proposal.source}:${proposal.name}`}>
                <Table.Td>
                  {canAdd(proposal) && (
                    <Checkbox
                      size='xs'
                      aria-label={`Add ${proposal.template_name}`}
                      checked={chosen.has(proposal.template_name)}
                      onChange={() => toggle(proposal.template_name)}
                    />
                  )}
                </Table.Td>
                <Table.Td>
                  {proposal.template_name}
                  {proposal.action === 'create' && (
                    <Badge ml={6} size='xs' color='blue' variant='outline'>
                      new template
                    </Badge>
                  )}
                </Table.Td>
                <Table.Td>
                  {proposal.action === 'keep' ? proposal.current : (proposal.value ?? proposal.found)}
                </Table.Td>
                <Table.Td>
                  <Text size='xs' c='dimmed'>
                    {SOURCE[proposal.source] ?? proposal.source}
                    {proposal.name !== proposal.template_name ? ` (${proposal.name}: ${proposal.found})` : ''}
                  </Text>
                </Table.Td>
                <Table.Td>
                  {proposal.action === 'keep' && (
                    <Text size='xs' c='dimmed'>
                      Already set
                    </Text>
                  )}
                  {proposal.action === 'skip' && (
                    <Text size='xs' c='orange'>
                      {proposal.reason}
                    </Text>
                  )}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
      <Group gap='sm'>
        {addable.length > 0 && (
          <Button
            size='xs'
            leftSection={<IconDatabaseImport size={14} />}
            loading={saving}
            disabled={chosen.size === 0}
            onClick={add}
          >
            Add {plural(chosen.size, 'parameter', 'parameters')}
          </Button>
        )}
        <Button size='xs' variant='default' loading={loading} onClick={find}>
          Look again
        </Button>
      </Group>
    </Stack>
  );
}
