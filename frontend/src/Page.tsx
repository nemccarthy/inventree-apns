import type { InvenTreePluginContext } from '@inventreedb/ui';
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Center,
  Drawer,
  Group,
  Loader,
  Paper,
  Progress,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Tabs,
  Text,
  TextInput,
  Title,
  Tooltip
} from '@mantine/core';
import {
  IconArrowsExchange,
  IconCopy,
  IconDatabase,
  IconLink,
  IconListDetails,
  IconRefresh,
  IconSearch,
  IconTrash
} from '@tabler/icons-react';
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { EnrichBox, sourcesNote } from './Enrich';
import { useActions } from './actions';
import { apiData, apiError, fmtDateTime, plural } from './api';
import type { Candidate, EnrichResult, Lookup, OverviewResult, PartLabel } from './types';
import {
  CompareTable,
  DirectionBadge,
  ExpandButton,
  LinkActions,
  PartName,
  Stock,
  StrengthBadge,
  numCell
} from './ui';

const TAB_KEY = 'inventree-apns-tab';
const TABS = ['candidates', 'links', 'boms', 'duplicates', 'data'];
const PAGE = 100;

function Kpi({
  label,
  value,
  hint,
  color
}: Readonly<{ label: string; value: string; hint?: string; color?: string }>) {
  return (
    <Paper withBorder p='sm'>
      <Text size='xs' c='dimmed' tt='uppercase' fw={600}>
        {label}
      </Text>
      <Text fz={26} fw={700} lh={1.2} c={color}>
        {value}
      </Text>
      {hint && (
        <Text size='xs' c='dimmed'>
          {hint}
        </Text>
      )}
    </Paper>
  );
}

function matches(part: PartLabel | undefined, needle: string): boolean {
  if (!part) {
    return false;
  }

  return [part.name, part.ipn, part.description, ...(part.mpns ?? []).map((item) => item.mpn)]
    .join(' ')
    .toLowerCase()
    .includes(needle);
}

/** The overview page, at /web/plugin/apns/overview */
export function ApnsPage({ context }: Readonly<{ context: InvenTreePluginContext }>) {
  const api = useRef(context.api);
  api.current = context.api;

  const slug = 'apns';

  const [data, setData] = useState<OverviewResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [tab, setTab] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [minimum, setMinimum] = useState<string | null>(null);
  const [shown, setShown] = useState(PAGE);
  const [enrich, setEnrich] = useState<number | null>(null);
  const [bulk, setBulk] = useState<{ done: number; total: number; added: number } | null>(null);
  const [bulkNote, setBulkNote] = useState<string | null>(null);
  const stopBulk = useRef(false);

  const reload = useCallback(() => setReloadKey((key) => key + 1), []);
  const actions = useActions(context, slug, reload);

  useEffect(() => {
    let cancelled = false;

    setLoading(true);
    setError(null);

    api.current
      .get(`/plugin/${slug}/overview/`, { params: reloadKey > 0 ? { fresh: 1 } : undefined })
      .then((response) => {
        if (!cancelled) {
          setData(apiData<OverviewResult>(response, 'summary'));
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(apiError(err, 'Could not load the alternates'));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  useEffect(() => {
    let stored: string | null = null;

    try {
      stored = window.localStorage.getItem(TAB_KEY);
    } catch {
      stored = null;
    }

    setTab(stored && TABS.includes(stored) ? stored : 'candidates');
  }, []);

  const changeTab = useCallback((value: string | null) => {
    setTab(value);
    setOpen(null);

    try {
      if (value) {
        window.localStorage.setItem(TAB_KEY, value);
      }
    } catch {
      // The choice of tab is just not remembered
    }
  }, []);

  const lookup: Lookup = useCallback(
    (pk) => (pk === null || pk === undefined ? undefined : data?.parts[String(pk)]),
    [data]
  );

  const candidates = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const floor = minimum ? Number(minimum) : 0;

    return (data?.candidates ?? []).filter(
      (item) =>
        item.strength >= floor &&
        (!needle || matches(lookup(item.part), needle) || matches(lookup(item.other), needle))
    );
  }, [data, search, minimum, lookup]);

  useEffect(() => setShown(PAGE), [search, minimum]);

  /** Add the parameters found for every part which is short of data */
  const enrichAll = useCallback(async () => {
    if (!data) {
      return;
    }

    const parts = data.thin.map((item) => item.part);
    let added = 0;
    let failed = 0;

    stopBulk.current = false;
    setBulkNote(null);
    setBulk({ done: 0, total: parts.length, added: 0 });

    for (let index = 0; index < parts.length; index++) {
      if (stopBulk.current) {
        break;
      }

      try {
        const response = await api.current.post(`/plugin/${slug}/enrich/`, {
          part: parts[index],
          apply: true
        });
        const result = apiData<EnrichResult>(response, 'proposals');

        added += result.applied?.added.length ?? 0;
        failed += result.report.some((item) => item.status === 'error') ? 1 : 0;
      } catch (err) {
        setBulkNote(apiError(err, 'Stopped'));
        break;
      }

      setBulk({ done: index + 1, total: parts.length, added });
    }

    setBulk(null);
    setBulkNote(
      (note) =>
        note ??
        `${plural(added, 'parameter', 'parameters')} added.` +
          (failed > 0 ? ` A supplier could not be reached for ${plural(failed, 'part', 'parts')}.` : '')
    );
    reload();
  }, [data, reload]);

  if (!data) {
    return error ? (
      <Alert color='red' title='Could not load the alternates' m='md'>
        {error}
      </Alert>
    ) : (
      <Center h={300}>
        <Loader />
      </Center>
    );
  }

  const may = data.permissions;
  const summary = data.summary;
  const unlinked = data.by_hand.filter((item) => !item.dismissed);

  const candidateRow = (entry: Candidate) => {
    const part = entry.part as number;
    const key = `${part}:${entry.other}`;
    const expanded = open === key;
    const a = lookup(part);
    const b = lookup(entry.other);

    return (
      <Fragment key={key}>
        <Table.Tr>
          <Table.Td w={28}>
            <ExpandButton open={expanded} onClick={() => setOpen(expanded ? null : key)} />
          </Table.Td>
          <Table.Td w={120}>
            <StrengthBadge match={entry} />
          </Table.Td>
          <Table.Td>
            <PartName context={context} part={a} />
          </Table.Td>
          <Table.Td>
            <Stock part={a} />
          </Table.Td>
          <Table.Td>
            <DirectionBadge
              direction={entry.direction}
              labels={{ forward: 'Can be replaced by', reverse: 'Can replace', both: 'Interchangeable with' }}
            />
          </Table.Td>
          <Table.Td>
            <PartName
              context={context}
              part={b}
              note={
                entry.substitute_on > 0 ? (
                  <Tooltip label={`Already set by hand as a substitute on ${plural(entry.substitute_on, 'BOM line', 'BOM lines')}`}>
                    <Badge size='xs' color='violet' variant='light'>
                      On {plural(entry.substitute_on, 'BOM', 'BOMs')}
                    </Badge>
                  </Tooltip>
                ) : undefined
              }
            />
          </Table.Td>
          <Table.Td>
            <Stock part={b} />
          </Table.Td>
          <Table.Td style={numCell}>{entry.used_in ?? 0}</Table.Td>
          <Table.Td>
            {may.link && (
              <LinkActions
                suggested={entry.direction}
                thisName={a?.name ?? 'the first part'}
                otherName={b?.name ?? 'the second part'}
                busy={actions.busy === key}
                onLink={(choice) => actions.link(part, entry.other, choice)}
                onDismiss={() => actions.dismiss(part, entry.other, true)}
              />
            )}
          </Table.Td>
        </Table.Tr>
        {expanded && (
          <Table.Tr>
            <Table.Td />
            <Table.Td colSpan={8}>
              <CompareTable rows={entry.rows} left={a?.name ?? 'First part'} right={b?.name ?? 'Second part'} />
            </Table.Td>
          </Table.Tr>
        )}
      </Fragment>
    );
  };

  return (
    <Stack gap='md' p='md'>
      <Group justify='space-between' align='flex-end'>
        <Stack gap={0}>
          <Title order={3}>Alternate parts</Title>
          <Text size='sm' c='dimmed'>
            {summary.eligible} of {plural(summary.parts, 'part', 'parts')} compared. Read{' '}
            {fmtDateTime(data.generated)}.
          </Text>
        </Stack>
        <Button
          variant='default'
          size='xs'
          leftSection={<IconRefresh size={14} />}
          loading={loading}
          onClick={reload}
        >
          Refresh
        </Button>
      </Group>

      {error && <Alert color='red'>{error}</Alert>}
      {actions.error && <Alert color='red'>{actions.error}</Alert>}
      {actions.message && <Alert color='teal'>{actions.message}</Alert>}

      <SimpleGrid cols={{ base: 2, sm: 3, lg: 5 }}>
        <Kpi label='Links' value={String(summary.links)} hint='Pairs of parts linked as alternates' />
        <Kpi
          label='Candidates'
          value={String(summary.candidates)}
          hint={`Matching at ${data.settings.min_strength}% or more`}
        />
        <Kpi
          label='BOM changes pending'
          value={String(summary.pending)}
          color={summary.pending > 0 ? 'yellow' : undefined}
          hint={summary.pending > 0 ? 'Substitutes to add or remove' : 'BOMs are in step with the links'}
        />
        <Kpi
          label='Duplicate MPNs'
          value={String(summary.duplicates)}
          color={summary.duplicates > 0 ? 'grape' : undefined}
          hint='One manufacturer part number under several parts'
        />
        <Kpi
          label='Short of data'
          value={String(summary.thin)}
          hint='Parts with fewer than two parameters to match on'
        />
      </SimpleGrid>

      <Tabs value={tab} onChange={changeTab} keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value='candidates' leftSection={<IconSearch size={14} />}>
            Candidates
          </Tabs.Tab>
          <Tabs.Tab value='links' leftSection={<IconLink size={14} />}>
            Links
          </Tabs.Tab>
          <Tabs.Tab value='boms' leftSection={<IconListDetails size={14} />}>
            BOMs
            {summary.pending + unlinked.length > 0 && (
              <Badge ml={6} size='xs' color='yellow' variant='filled'>
                {summary.pending + unlinked.length}
              </Badge>
            )}
          </Tabs.Tab>
          <Tabs.Tab value='duplicates' leftSection={<IconCopy size={14} />}>
            Duplicates
          </Tabs.Tab>
          <Tabs.Tab value='data' leftSection={<IconDatabase size={14} />}>
            Part data
          </Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value='candidates' pt='md'>
          <Stack gap='sm'>
            <Group gap='sm'>
              <TextInput
                placeholder='Filter by name, IPN or MPN'
                leftSection={<IconSearch size={14} />}
                value={search}
                onChange={(event) => setSearch(event.currentTarget.value)}
                w={280}
              />
              <Select
                placeholder='Any strength'
                clearable
                value={minimum}
                onChange={setMinimum}
                data={[
                  { value: '95', label: '95% and up' },
                  { value: '90', label: '90% and up' },
                  { value: '80', label: '80% and up' },
                  { value: '70', label: '70% and up' }
                ]}
                w={160}
              />
              <Text size='sm' c='dimmed'>
                {plural(candidates.length, 'pair', 'pairs')}, strongest first
              </Text>
            </Group>
            {candidates.length === 0 ? (
              <Text size='sm' c='dimmed'>
                {data.candidates.length === 0
                  ? 'No two parts match closely enough to be alternates. Parts are matched on their parameters: see the Part data tab for parts which have too few.'
                  : 'No candidates match the filter.'}
              </Text>
            ) : (
              <Table verticalSpacing='xs' highlightOnHover>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th />
                    <Table.Th>Match</Table.Th>
                    <Table.Th>Part</Table.Th>
                    <Table.Th style={numCell}>In stock</Table.Th>
                    <Table.Th />
                    <Table.Th>Part</Table.Th>
                    <Table.Th style={numCell}>In stock</Table.Th>
                    <Table.Th style={numCell}>
                      <Tooltip label='BOM lines which use either part'>
                        <span>BOM lines</span>
                      </Tooltip>
                    </Table.Th>
                    <Table.Th />
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>{candidates.slice(0, shown).map(candidateRow)}</Table.Tbody>
              </Table>
            )}
            {candidates.length > shown && (
              <Group justify='center'>
                <Button variant='default' size='xs' onClick={() => setShown(shown + PAGE)}>
                  Show more ({candidates.length - shown} left)
                </Button>
              </Group>
            )}
          </Stack>
        </Tabs.Panel>

        <Tabs.Panel value='links' pt='md'>
          {data.links.length === 0 ? (
            <Text size='sm' c='dimmed'>
              No parts are linked yet. Link pairs from the Candidates tab, or from the
              Alternates panel of a part.
            </Text>
          ) : (
            <Table verticalSpacing='xs' highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th />
                  <Table.Th>Part</Table.Th>
                  <Table.Th />
                  <Table.Th>Alternate</Table.Th>
                  <Table.Th>Match</Table.Th>
                  <Table.Th>Note</Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {data.links.map((entry) => {
                  const part = entry.part as number;
                  const key = `${part}:${entry.other}`;
                  const expanded = open === key;
                  const a = lookup(part);
                  const b = lookup(entry.other);

                  return (
                    <Fragment key={key}>
                      <Table.Tr>
                        <Table.Td w={28}>
                          <ExpandButton open={expanded} onClick={() => setOpen(expanded ? null : key)} />
                        </Table.Td>
                        <Table.Td>
                          <PartName context={context} part={a} />
                        </Table.Td>
                        <Table.Td>
                          <DirectionBadge
                            direction={entry.relation}
                            labels={{ forward: 'Can be replaced by', both: 'Interchangeable with' }}
                          />
                        </Table.Td>
                        <Table.Td>
                          <PartName context={context} part={b} />
                        </Table.Td>
                        <Table.Td>
                          <Group gap={6}>
                            {entry.match?.direction === 'none' ? (
                              <Tooltip label='The parameters of the two parts say they are not alternates. Open the comparison to see where they differ.'>
                                <Badge color='red' variant='outline'>
                                  Check
                                </Badge>
                              </Tooltip>
                            ) : (
                              <StrengthBadge match={entry.match} />
                            )}
                            {entry.problems.map((problem) => (
                              <Badge key={problem} color='orange' variant='light'>
                                {problem}
                              </Badge>
                            ))}
                          </Group>
                        </Table.Td>
                        <Table.Td>
                          <Text size='sm'>{entry.note}</Text>
                          <Text size='xs' c='dimmed'>
                            {[entry.by, entry.at.slice(0, 10)].filter(Boolean).join(', ')}
                          </Text>
                        </Table.Td>
                        <Table.Td style={{ textAlign: 'right' }}>
                          {may.link && (
                            <Group gap={4} justify='flex-end' wrap='nowrap'>
                              <Button
                                size='compact-sm'
                                variant='subtle'
                                loading={actions.busy === key}
                                onClick={() =>
                                  actions.link(part, entry.other, entry.two_way ? 'forward' : 'both', entry.note)
                                }
                              >
                                Make {entry.two_way ? 'one-way' : 'two-way'}
                              </Button>
                              <Tooltip label='Remove the link'>
                                <ActionIcon
                                  variant='subtle'
                                  color='red'
                                  aria-label='Remove the link'
                                  onClick={() => actions.unlink(part, entry.other)}
                                >
                                  <IconTrash size={16} />
                                </ActionIcon>
                              </Tooltip>
                            </Group>
                          )}
                        </Table.Td>
                      </Table.Tr>
                      {expanded && (
                        <Table.Tr>
                          <Table.Td />
                          <Table.Td colSpan={6}>
                            <CompareTable
                              rows={entry.match?.rows}
                              left={a?.name ?? 'Part'}
                              right={b?.name ?? 'Alternate'}
                            />
                          </Table.Td>
                        </Table.Tr>
                      )}
                    </Fragment>
                  );
                })}
              </Table.Tbody>
            </Table>
          )}
        </Tabs.Panel>

        <Tabs.Panel value='boms' pt='md'>
          <Stack gap='lg'>
            <Stack gap='xs'>
              <Group justify='space-between'>
                <Text fw={600}>Changes waiting for a sync</Text>
                {may.sync && summary.pending > 0 && (
                  <Button
                    size='xs'
                    leftSection={<IconArrowsExchange size={14} />}
                    loading={actions.busy === 'sync'}
                    onClick={() => actions.sync()}
                  >
                    Sync all BOMs
                  </Button>
                )}
              </Group>
              <Text size='sm' c='dimmed'>
                Every link is copied to the BOM lines of its part as a substitute, so that
                build orders and stock checks can use the alternate.{' '}
                {data.settings.auto_sync
                  ? 'This happens as soon as a link changes.'
                  : 'Automatic updates are turned off in the plugin settings, so this only happens when you sync.'}{' '}
                Substitutes which were added by hand are never changed.
              </Text>
              {data.sync.lines.length === 0 ? (
                <Text size='sm'>
                  Every one of the {plural(summary.bom_lines, 'BOM line', 'BOM lines')} is in step with
                  the links.
                </Text>
              ) : (
                <Table verticalSpacing='xs'>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>Assembly</Table.Th>
                      <Table.Th>BOM line</Table.Th>
                      <Table.Th>Change</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {data.sync.lines.map((change) => (
                      <Table.Tr key={change.line}>
                        <Table.Td>
                          <PartName context={context} part={lookup(change.assembly)} />
                        </Table.Td>
                        <Table.Td>
                          <PartName
                            context={context}
                            part={lookup(change.sub_part)}
                            note={
                              change.reference ? (
                                <Text size='xs' c='dimmed'>
                                  {change.reference}
                                </Text>
                              ) : undefined
                            }
                          />
                        </Table.Td>
                        <Table.Td>
                          <Group gap={6}>
                            {change.add.map((pk) => (
                              <Badge key={`a${pk}`} color='teal' variant='light' tt='none'>
                                + {lookup(pk)?.name ?? `Part ${pk}`}
                              </Badge>
                            ))}
                            {change.remove.map((pk) => (
                              <Badge key={`r${pk}`} color='red' variant='light' tt='none'>
                                - {lookup(pk)?.name ?? `Part ${pk}`}
                              </Badge>
                            ))}
                            {change.skipped && (
                              <Badge color='gray' variant='outline'>
                                Locked: left alone
                              </Badge>
                            )}
                          </Group>
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              )}
              {data.sync.more > 0 && (
                <Text size='sm' c='dimmed'>
                  And {plural(data.sync.more, 'more BOM line', 'more BOM lines')}.
                </Text>
              )}
            </Stack>

            <Stack gap='xs'>
              <Text fw={600}>Substitutes set by hand</Text>
              <Text size='sm' c='dimmed'>
                These substitutes were added on a BOM directly and are not links. Linking
                one applies it to every BOM which uses the part.
              </Text>
              {data.by_hand.length === 0 ? (
                <Text size='sm'>None.</Text>
              ) : (
                <Table verticalSpacing='xs'>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>Part</Table.Th>
                      <Table.Th>Substitute</Table.Th>
                      <Table.Th style={numCell}>Set on</Table.Th>
                      <Table.Th style={numCell}>Missing on</Table.Th>
                      <Table.Th />
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {data.by_hand.map((item) => {
                      const key = `${item.part}:${item.other}`;

                      return (
                        <Table.Tr key={key}>
                          <Table.Td>
                            <PartName context={context} part={lookup(item.part)} />
                          </Table.Td>
                          <Table.Td>
                            <PartName context={context} part={lookup(item.other)} />
                          </Table.Td>
                          <Table.Td style={numCell}>{plural(item.lines, 'BOM line', 'BOM lines')}</Table.Td>
                          <Table.Td style={numCell}>
                            <Text size='sm' c={item.missing > 0 ? 'yellow' : 'dimmed'}>
                              {plural(item.missing, 'BOM line', 'BOM lines')}
                            </Text>
                          </Table.Td>
                          <Table.Td>
                            {may.link &&
                              (item.dismissed ? (
                                <Group justify='flex-end'>
                                  <Button
                                    size='compact-sm'
                                    variant='subtle'
                                    loading={actions.busy === key}
                                    onClick={() => actions.dismiss(item.part, item.other, false)}
                                  >
                                    Show again
                                  </Button>
                                </Group>
                              ) : (
                                <LinkActions
                                  suggested='forward'
                                  thisName={lookup(item.part)?.name ?? 'the part'}
                                  otherName={lookup(item.other)?.name ?? 'the substitute'}
                                  busy={actions.busy === key}
                                  onLink={(choice) => actions.link(item.part, item.other, choice)}
                                  onDismiss={() => actions.dismiss(item.part, item.other, true)}
                                />
                              ))}
                          </Table.Td>
                        </Table.Tr>
                      );
                    })}
                  </Table.Tbody>
                </Table>
              )}
            </Stack>
          </Stack>
        </Tabs.Panel>

        <Tabs.Panel value='duplicates' pt='md'>
          <Stack gap='xs'>
            <Text size='sm' c='dimmed'>
              The same manufacturer part number held under more than one part. These are
              usually the same physical part entered twice: link them two-way, or merge
              them into one part.
            </Text>
            {data.duplicates.length === 0 ? (
              <Text size='sm'>No manufacturer part number is held under more than one part.</Text>
            ) : (
              <Table verticalSpacing='xs'>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>MPN</Table.Th>
                    <Table.Th>Parts</Table.Th>
                    <Table.Th />
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {data.duplicates.map((item) => {
                    const [first, second] = item.parts;
                    const key = `${first}:${second}`;
                    const linked = data.links.some(
                      (link) =>
                        item.parts.includes(link.part as number) && item.parts.includes(link.other)
                    );

                    return (
                      <Table.Tr key={item.mpn}>
                        <Table.Td>
                          <Text size='sm' ff='monospace'>
                            {item.mpn}
                          </Text>
                        </Table.Td>
                        <Table.Td>
                          <Stack gap={4}>
                            {item.parts.map((pk) => (
                              <Group key={pk} gap='md' wrap='nowrap'>
                                <PartName context={context} part={lookup(pk)} />
                                <Text size='xs' c='dimmed'>
                                  {plural(data.usage[String(pk)] ?? 0, 'BOM line', 'BOM lines')}
                                </Text>
                              </Group>
                            ))}
                          </Stack>
                        </Table.Td>
                        <Table.Td style={{ textAlign: 'right' }}>
                          {linked ? (
                            <Badge color='teal' variant='light'>
                              Linked
                            </Badge>
                          ) : (
                            may.link &&
                            item.parts.length === 2 && (
                              <Button
                                size='compact-sm'
                                variant='light'
                                leftSection={<IconLink size={14} />}
                                loading={actions.busy === key}
                                onClick={() => actions.link(first, second, 'both', 'Same MPN')}
                              >
                                Link two-way
                              </Button>
                            )
                          )}
                        </Table.Td>
                      </Table.Tr>
                    );
                  })}
                </Table.Tbody>
              </Table>
            )}
          </Stack>
        </Tabs.Panel>

        <Tabs.Panel value='data' pt='md'>
          <Stack gap='sm'>
            <Text size='sm' c='dimmed'>
              Parts are matched on their parameters. These parts have fewer than two
              parameters the matching can use, so they are matched on what can be read
              from their name and description, or not at all. Parts on the most BOM
              lines come first. {sourcesNote(data.settings)}
            </Text>
            {bulkNote && <Alert color='teal'>{bulkNote}</Alert>}
            {bulk && (
              <Stack gap={4}>
                <Progress value={(100 * bulk.done) / Math.max(1, bulk.total)} />
                <Group justify='space-between'>
                  <Text size='sm'>
                    {bulk.done} of {plural(bulk.total, 'part', 'parts')} looked up,{' '}
                    {plural(bulk.added, 'parameter', 'parameters')} added
                  </Text>
                  <Button
                    size='compact-sm'
                    variant='default'
                    onClick={() => {
                      stopBulk.current = true;
                    }}
                  >
                    Stop
                  </Button>
                </Group>
              </Stack>
            )}
            {data.thin.length === 0 ? (
              <Text size='sm'>Every part has parameters to match on.</Text>
            ) : (
              <>
                {may.enrich && !bulk && (
                  <Group gap='sm'>
                    <Button size='xs' leftSection={<IconDatabase size={14} />} onClick={enrichAll}>
                      Find and add parameters for {data.thin.length < summary.thin ? 'the first ' : 'all '}
                      {plural(data.thin.length, 'part', 'parts')}
                    </Button>
                    <Text size='xs' c='dimmed'>
                      Adds every value found. Parameters a part already has are not changed.
                    </Text>
                  </Group>
                )}
                <Table verticalSpacing='xs'>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>Part</Table.Th>
                      <Table.Th>Category</Table.Th>
                      <Table.Th style={numCell}>BOM lines</Table.Th>
                      <Table.Th style={numCell}>Parameters used</Table.Th>
                      <Table.Th style={numCell}>Read from text</Table.Th>
                      <Table.Th />
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {data.thin.slice(0, shown).map((item) => {
                      const part = lookup(item.part);

                      return (
                        <Table.Tr key={item.part}>
                          <Table.Td>
                            <PartName context={context} part={part} />
                          </Table.Td>
                          <Table.Td>
                            <Text size='sm'>{part?.category_name}</Text>
                          </Table.Td>
                          <Table.Td style={numCell}>{item.used_in}</Table.Td>
                          <Table.Td style={numCell}>{part?.known ?? 0}</Table.Td>
                          <Table.Td style={numCell}>{part?.derived ?? 0}</Table.Td>
                          <Table.Td style={{ textAlign: 'right' }}>
                            {may.enrich && (
                              <Button size='compact-sm' variant='subtle' onClick={() => setEnrich(item.part)}>
                                Find parameters
                              </Button>
                            )}
                          </Table.Td>
                        </Table.Tr>
                      );
                    })}
                  </Table.Tbody>
                </Table>
                {data.thin.length > shown && (
                  <Group justify='center'>
                    <Button variant='default' size='xs' onClick={() => setShown(shown + PAGE)}>
                      Show more ({data.thin.length - shown} left)
                    </Button>
                  </Group>
                )}
              </>
            )}
          </Stack>
        </Tabs.Panel>
      </Tabs>

      <Drawer
        opened={enrich !== null}
        onClose={() => setEnrich(null)}
        position='right'
        size='xl'
        title={
          <Text fw={600}>{enrich !== null ? (lookup(enrich)?.name ?? 'Part') : ''}</Text>
        }
      >
        {enrich !== null && (
          <EnrichBox
            context={context}
            slug={slug}
            part={enrich}
            settings={data.settings}
            onAdded={reload}
            autoStart
          />
        )}
      </Drawer>
    </Stack>
  );
}
