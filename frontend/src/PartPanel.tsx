import type { InvenTreePluginContext } from '@inventreedb/ui';
import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Button,
  Center,
  Group,
  Loader,
  Menu,
  Stack,
  Table,
  Text,
  Tooltip
} from '@mantine/core';
import {
  IconArrowsExchange,
  IconDots,
  IconLock,
  IconRefresh,
  IconTrash
} from '@tabler/icons-react';
import { Fragment, useCallback, useEffect, useRef, useState } from 'react';

import { EnrichBox } from './Enrich';
import { useActions } from './actions';
import { apiData, apiError, plural } from './api';
import type { Candidate, LinkEntry, Lookup, PartResult } from './types';
import {
  AppLink,
  CompareTable,
  DirectionBadge,
  ExpandButton,
  LinkActions,
  PartName,
  SectionTitle,
  Stock,
  StrengthBadge,
  numCell
} from './ui';

/** Alternates panel on a part page */
export function ApnsPartPanel({ context }: Readonly<{ context: InvenTreePluginContext }>) {
  const api = useRef(context.api);
  api.current = context.api;

  const partId: number | null = context.context?.part_id ?? context.id ?? null;
  const slug: string = context.context?.slug ?? 'apns';

  const [data, setData] = useState<PartResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [open, setOpen] = useState<number | null>(null);
  const [showDismissed, setShowDismissed] = useState(false);

  const reload = useCallback(() => setReloadKey((key) => key + 1), []);
  const actions = useActions(context, slug, reload);

  useEffect(() => {
    if (partId === null || partId === undefined) {
      setLoading(false);
      setError('No part is associated with this page');
      return;
    }

    let cancelled = false;

    setLoading(true);
    setError(null);

    api.current
      // After the first load, always read the parts afresh
      .get(`/plugin/${slug}/part/${partId}/`, {
        params: reloadKey > 0 ? { fresh: 1 } : undefined
      })
      .then((response) => {
        if (!cancelled) {
          setData(apiData<PartResult>(response, 'part'));
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(apiError(err, 'Could not load the alternates of this part'));
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
  }, [partId, slug, reloadKey]);

  const lookup: Lookup = useCallback(
    (pk) => (pk === null || pk === undefined ? undefined : data?.parts[String(pk)]),
    [data]
  );

  if (!data) {
    return error ? (
      <Alert color='red' title='Could not load the alternates'>
        {error}
      </Alert>
    ) : (
      <Center h={200}>
        <Loader />
      </Center>
    );
  }

  const me = data.part;
  const may = data.permissions;
  const busyFor = (other: number) => actions.busy === `${me.pk}:${other}`;

  const linkRow = (entry: LinkEntry) => {
    const other = lookup(entry.other);
    const expanded = open === entry.other;
    const disagree = entry.match?.direction === 'none';

    return (
      <Fragment key={entry.other}>
        <Table.Tr>
          <Table.Td w={28}>
            <ExpandButton open={expanded} onClick={() => setOpen(expanded ? null : entry.other)} />
          </Table.Td>
          <Table.Td>
            <PartName context={context} part={other} />
          </Table.Td>
          <Table.Td>
            <Group gap={6}>
              <DirectionBadge direction={entry.relation} />
              {disagree && (
                <Tooltip label='The parameters of the two parts say they are not alternates. Open the comparison to see where they differ.'>
                  <Badge color='red' variant='outline'>
                    Check
                  </Badge>
                </Tooltip>
              )}
              {entry.problems.map((problem) => (
                <Badge key={problem} color='orange' variant='light'>
                  {problem}
                </Badge>
              ))}
            </Group>
          </Table.Td>
          <Table.Td>
            <Stock part={other} />
          </Table.Td>
          <Table.Td>
            <Text size='sm'>{entry.note}</Text>
            <Text size='xs' c='dimmed'>
              {[entry.by, entry.at.slice(0, 10)].filter(Boolean).join(', ')}
            </Text>
          </Table.Td>
          <Table.Td style={{ textAlign: 'right' }}>
            {may.link && (
              <Menu position='bottom-end' withinPortal>
                <Menu.Target>
                  <ActionIcon
                    variant='subtle'
                    color='gray'
                    aria-label='Change this link'
                    loading={busyFor(entry.other)}
                  >
                    <IconDots size={16} />
                  </ActionIcon>
                </Menu.Target>
                <Menu.Dropdown>
                  <Menu.Label>Change to</Menu.Label>
                  {entry.relation !== 'both' && (
                    <Menu.Item onClick={() => actions.link(me.pk, entry.other, 'both', entry.note)}>
                      Two-way: interchangeable
                    </Menu.Item>
                  )}
                  {entry.relation !== 'forward' && (
                    <Menu.Item onClick={() => actions.link(me.pk, entry.other, 'forward', entry.note)}>
                      One-way: {other?.name} can replace this part
                    </Menu.Item>
                  )}
                  {entry.relation !== 'reverse' && (
                    <Menu.Item onClick={() => actions.link(me.pk, entry.other, 'reverse', entry.note)}>
                      One-way: this part can replace {other?.name}
                    </Menu.Item>
                  )}
                  <Menu.Divider />
                  <Menu.Item
                    color='red'
                    leftSection={<IconTrash size={14} />}
                    onClick={() => actions.unlink(me.pk, entry.other)}
                  >
                    Remove the link
                  </Menu.Item>
                </Menu.Dropdown>
              </Menu>
            )}
          </Table.Td>
        </Table.Tr>
        {expanded && (
          <Table.Tr>
            <Table.Td />
            <Table.Td colSpan={5}>
              <CompareTable rows={entry.match?.rows} left='This part' right={other?.name ?? 'Other part'} />
            </Table.Td>
          </Table.Tr>
        )}
      </Fragment>
    );
  };

  const candidateRow = (entry: Candidate, dismissed: boolean) => {
    const other = lookup(entry.other);
    const expanded = open === entry.other;

    return (
      <Fragment key={entry.other}>
        <Table.Tr>
          <Table.Td w={28}>
            <ExpandButton open={expanded} onClick={() => setOpen(expanded ? null : entry.other)} />
          </Table.Td>
          <Table.Td w={120}>
            <StrengthBadge match={entry} />
          </Table.Td>
          <Table.Td>
            <PartName
              context={context}
              part={other}
              note={
                entry.substitute_on > 0 ? (
                  <Tooltip
                    label={`Set by hand as a substitute for this part on ${plural(entry.substitute_on, 'BOM line', 'BOM lines')}, out of ${data.bom_lines}`}
                  >
                    <Badge size='xs' color='violet' variant='light'>
                      On {plural(entry.substitute_on, 'BOM', 'BOMs')}
                    </Badge>
                  </Tooltip>
                ) : undefined
              }
            />
          </Table.Td>
          <Table.Td>
            <DirectionBadge direction={entry.direction} />
          </Table.Td>
          <Table.Td>
            <Stock part={other} />
          </Table.Td>
          <Table.Td>
            {may.link &&
              (dismissed ? (
                <Group justify='flex-end'>
                  <Button
                    size='compact-sm'
                    variant='subtle'
                    loading={busyFor(entry.other)}
                    onClick={() => actions.dismiss(me.pk, entry.other, false)}
                  >
                    Show again
                  </Button>
                </Group>
              ) : (
                <LinkActions
                  suggested={entry.direction}
                  thisName='this part'
                  otherName={other?.name ?? 'the other part'}
                  busy={busyFor(entry.other)}
                  onLink={(choice) => actions.link(me.pk, entry.other, choice)}
                  onDismiss={() => actions.dismiss(me.pk, entry.other, true)}
                />
              ))}
          </Table.Td>
        </Table.Tr>
        {expanded && (
          <Table.Tr>
            <Table.Td />
            <Table.Td colSpan={5}>
              <CompareTable rows={entry.rows} left='This part' right={other?.name ?? 'Other part'} />
            </Table.Td>
          </Table.Tr>
        )}
      </Fragment>
    );
  };

  const real = data.attributes.filter((item) => !item.derived);

  return (
    <Stack gap='lg'>
      <Group justify='space-between'>
        <Text size='sm' c='dimmed'>
          {plural(data.links.length, 'linked alternate', 'linked alternates')},{' '}
          {plural(data.candidates.length, 'candidate', 'candidates')}, used on{' '}
          {plural(data.bom_lines, 'BOM line', 'BOM lines')}.
        </Text>
        <Group gap='sm'>
          <AppLink context={context} to={`/plugin/${slug}/overview`}>
            <Group gap={4} wrap='nowrap'>
              <IconArrowsExchange size={14} />
              All alternates
            </Group>
          </AppLink>
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
      </Group>

      {error && <Alert color='red'>{error}</Alert>}
      {actions.error && <Alert color='red'>{actions.error}</Alert>}
      {actions.message && <Alert color='teal'>{actions.message}</Alert>}

      {data.pending > 0 && (
        <Alert color='yellow' title='The BOMs are out of step with the links'>
          <Group justify='space-between'>
            <Text size='sm'>
              {plural(data.pending, 'substitute has', 'substitutes have')} to be added or
              removed on the BOM lines for this part.
            </Text>
            {may.sync && (
              <Button size='xs' loading={actions.busy === 'sync'} onClick={() => actions.sync([me.pk])}>
                Sync now
              </Button>
            )}
          </Group>
        </Alert>
      )}

      {!me.eligible && (
        <Alert color='gray'>
          Candidates are not looked for on this part: it is{' '}
          {me.active === false ? 'inactive' : 'an assembly, a template, virtual or not a component'}.
          It can still be linked from another part.
        </Alert>
      )}

      <Stack gap='xs'>
        <SectionTitle count={data.links.length}>Alternates</SectionTitle>
        {data.links.length === 0 ? (
          <Text size='sm' c='dimmed'>
            No alternates are linked to this part yet. Link one of the candidates below.
          </Text>
        ) : (
          <Table verticalSpacing='xs'>
            <Table.Thead>
              <Table.Tr>
                <Table.Th />
                <Table.Th>Part</Table.Th>
                <Table.Th>Link</Table.Th>
                <Table.Th style={numCell}>In stock</Table.Th>
                <Table.Th>Note</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>{data.links.map(linkRow)}</Table.Tbody>
          </Table>
        )}
      </Stack>

      <Stack gap='xs'>
        <SectionTitle count={data.candidates.length}>Candidates</SectionTitle>
        {data.candidates.length === 0 ? (
          <Text size='sm' c='dimmed'>
            No other part matches this one at {data.settings.min_strength}% or more.
            {real.length < 2
              ? ' This part has few parameters to match on: add its value, package and ratings below.'
              : ''}
          </Text>
        ) : (
          <Table verticalSpacing='xs'>
            <Table.Thead>
              <Table.Tr>
                <Table.Th />
                <Table.Th>Match</Table.Th>
                <Table.Th>Part</Table.Th>
                <Table.Th>Suggested link</Table.Th>
                <Table.Th style={numCell}>In stock</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>{data.candidates.map((entry) => candidateRow(entry, false))}</Table.Tbody>
          </Table>
        )}
        {data.dismissed.length > 0 && (
          <>
            <Anchor component='button' type='button' size='sm' ta='left' onClick={() => setShowDismissed(!showDismissed)}>
              {showDismissed ? 'Hide' : 'Show'} {plural(data.dismissed.length, 'hidden candidate', 'hidden candidates')}
            </Anchor>
            {showDismissed && (
              <Table verticalSpacing='xs'>
                <Table.Tbody>{data.dismissed.map((entry) => candidateRow(entry, true))}</Table.Tbody>
              </Table>
            )}
          </>
        )}
      </Stack>

      <Stack gap='xs'>
        <SectionTitle count={data.usage.length}>Used on</SectionTitle>
        {data.usage.length === 0 ? (
          <Text size='sm' c='dimmed'>
            This part is not on any BOM.
          </Text>
        ) : (
          <Table verticalSpacing='xs'>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Assembly</Table.Th>
                <Table.Th>Reference</Table.Th>
                <Table.Th>Substitutes on the BOM line</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {data.usage.map((line) => (
                <Table.Tr key={line.line}>
                  <Table.Td>
                    <PartName
                      context={context}
                      part={lookup(line.assembly)}
                      note={
                        line.locked ? (
                          <Tooltip label='This assembly is locked'>
                            <IconLock size={14} />
                          </Tooltip>
                        ) : undefined
                      }
                    />
                  </Table.Td>
                  <Table.Td>
                    <Text size='sm'>{line.reference}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Group gap={6}>
                      {line.substitutes.length === 0 && line.add.length === 0 && (
                        <Text size='sm' c='dimmed'>
                          None
                        </Text>
                      )}
                      {line.substitutes.map((item) => (
                        <Tooltip
                          key={item.part}
                          label={
                            line.remove.includes(item.part)
                              ? 'No longer linked: will be removed by the next sync'
                              : item.managed
                                ? 'Added from a link'
                                : 'Added by hand on this BOM: never changed by this plugin'
                          }
                        >
                          <Badge
                            color={line.remove.includes(item.part) ? 'red' : item.managed ? 'teal' : 'violet'}
                            variant='light'
                            tt='none'
                          >
                            {lookup(item.part)?.name ?? `Part ${item.part}`}
                            {item.managed ? '' : ' (by hand)'}
                          </Badge>
                        </Tooltip>
                      ))}
                      {line.add.map((pk) => (
                        <Tooltip
                          key={pk}
                          label={line.skipped ? 'Not added: the assembly is locked' : 'Linked: will be added by the next sync'}
                        >
                          <Badge color='yellow' variant='outline' tt='none'>
                            + {lookup(pk)?.name ?? `Part ${pk}`}
                          </Badge>
                        </Tooltip>
                      ))}
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}
      </Stack>

      <Stack gap='xs'>
        <SectionTitle>Matched on</SectionTitle>
        {data.attributes.length === 0 ? (
          <Text size='sm' c='dimmed'>
            This part has no parameters which the matching can use, so it is matched on
            its name alone.
          </Text>
        ) : (
          <Group gap={6}>
            {data.attributes.map((item) => (
              <Tooltip
                key={item.key}
                label={
                  item.derived
                    ? 'Read from the name or description. Add it as a parameter for a firmer match.'
                    : 'From a parameter of the part'
                }
              >
                <Badge color={item.derived ? 'gray' : 'blue'} variant={item.derived ? 'outline' : 'light'} tt='none'>
                  {item.label}: {item.text}
                </Badge>
              </Tooltip>
            ))}
          </Group>
        )}
        {may.enrich && (
          <EnrichBox
            context={context}
            slug={slug}
            part={me.pk}
            settings={data.settings}
            onAdded={reload}
          />
        )}
      </Stack>
    </Stack>
  );
}
