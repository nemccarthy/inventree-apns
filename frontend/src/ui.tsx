import type { InvenTreePluginContext } from '@inventreedb/ui';
import {
  ActionIcon,
  Anchor,
  Badge,
  Button,
  Group,
  Menu,
  Paper,
  Stack,
  Table,
  Text,
  Tooltip
} from '@mantine/core';
import {
  IconArrowLeft,
  IconArrowRight,
  IconArrowsExchange,
  IconChevronDown,
  IconChevronRight,
  IconEyeOff
} from '@tabler/icons-react';
import type { CSSProperties, ReactNode } from 'react';

import { fmtQty } from './api';
import type { CompareRow, Direction, MatchInfo, PartLabel, Verdict } from './types';

/** Right-aligned numeric table cell */
export const numCell: CSSProperties = {
  textAlign: 'right',
  fontVariantNumeric: 'tabular-nums',
  whiteSpace: 'nowrap'
};

export function partUrl(pk: number): string {
  return `/part/${pk}/`;
}

/** A link which navigates inside the InvenTree single page app */
export function AppLink({
  context,
  to,
  children,
  title
}: Readonly<{
  context: InvenTreePluginContext;
  to: string;
  children: ReactNode;
  title?: string;
}>) {
  return (
    <Anchor
      href={`/web${to}`}
      title={title}
      size='sm'
      onClick={(event) => {
        // Let the browser handle ctrl / cmd / middle click (open in a new tab)
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) {
          return;
        }

        event.preventDefault();
        context.navigate(to);
      }}
    >
      {children}
    </Anchor>
  );
}

/**
 * A part, linked to its page: the manufacturer and MPN first, with the part
 * name (and IPN) below. A part with no MPN is shown by its name.
 */
export function PartName({
  context,
  part,
  note
}: Readonly<{
  context: InvenTreePluginContext;
  part: PartLabel | undefined;
  note?: ReactNode;
}>) {
  if (!part) {
    return <Text size='sm'>Unknown part</Text>;
  }

  const mpn = part.mpns?.[0];
  const number = mpn ? `${mpn.manufacturer} ${mpn.mpn}`.trim() : '';
  const more = (part.mpns?.length ?? 0) - 1;
  const below = number ? [part.name, part.ipn].filter(Boolean) : [part.ipn].filter(Boolean);

  return (
    <Stack gap={0}>
      <Group gap={6} wrap='nowrap'>
        <AppLink context={context} to={partUrl(part.pk)} title={part.description}>
          {number || part.name}
        </AppLink>
        {more > 0 && (
          <Tooltip label={(part.mpns ?? []).slice(1).map((item) => `${item.manufacturer} ${item.mpn}`.trim()).join(', ')}>
            <Badge size='xs' color='gray' variant='light'>
              +{more}
            </Badge>
          </Tooltip>
        )}
        {part.active === false && (
          <Badge size='xs' color='gray' variant='light'>
            Inactive
          </Badge>
        )}
        {note}
      </Group>
      {below.length > 0 && (
        <Text size='xs' c='dimmed'>
          {below.join(' · ')}
        </Text>
      )}
    </Stack>
  );
}

/** What a part is headed by: its manufacturer and MPN, or its name */
export function partTitle(part: PartLabel | undefined): string | undefined {
  const mpn = part?.mpns?.[0];

  return mpn ? `${mpn.manufacturer} ${mpn.mpn}`.trim() : part?.name;
}

export function Stock({ part }: Readonly<{ part: PartLabel | undefined }>) {
  if (!part || part.stock === undefined) {
    return null;
  }

  return (
    <Text size='sm' c={part.stock > 0 ? undefined : 'dimmed'} style={numCell}>
      {fmtQty(part.stock)}
    </Text>
  );
}

function strengthColor(strength: number): string {
  if (strength >= 90) {
    return 'teal';
  }

  return strength >= 75 ? 'blue' : 'gray';
}

const BASIS: Record<string, string> = {
  parameters: 'Compared on their parameters',
  name: 'Only the names are alike: there are no parameters to compare',
  mpn: 'Both hold the same manufacturer part number',
  bom: 'Already used as a substitute on a BOM'
};

export function StrengthBadge({ match }: Readonly<{ match: MatchInfo | null | undefined }>) {
  if (!match) {
    return null;
  }

  const coverage =
    match.coverage !== undefined && match.basis === 'parameters'
      ? ` ${Math.round(match.coverage * 100)}% of the attributes are known for both parts.`
      : '';

  return (
    <Tooltip label={`${BASIS[match.basis] ?? ''}.${coverage}`} multiline maw={320}>
      <Badge
        color={match.same_mpn ? 'grape' : strengthColor(match.strength)}
        variant={match.basis === 'name' ? 'outline' : 'light'}
        style={{ fontVariantNumeric: 'tabular-nums', flexShrink: 0 }}
      >
        {match.same_mpn ? 'Same MPN' : `${match.strength}%`}
      </Badge>
    </Tooltip>
  );
}

const DIRECTION: Record<Direction, { label: string; color: string }> = {
  both: { label: 'Interchangeable', color: 'teal' },
  forward: { label: 'Can replace this part', color: 'blue' },
  reverse: { label: 'This part can replace it', color: 'indigo' },
  none: { label: 'Parameters disagree', color: 'red' }
};

/** How the other part relates to this one */
export function DirectionBadge({
  direction,
  labels
}: Readonly<{ direction: Direction; labels?: Partial<Record<Direction, string>> }>) {
  const info = DIRECTION[direction] ?? DIRECTION.none;
  const icon =
    direction === 'both' ? (
      <IconArrowsExchange size={12} />
    ) : direction === 'forward' ? (
      <IconArrowLeft size={12} />
    ) : direction === 'reverse' ? (
      <IconArrowRight size={12} />
    ) : undefined;

  return (
    <Badge color={info.color} variant='light' leftSection={icon} style={{ flexShrink: 0, minWidth: 'max-content' }}>
      {labels?.[direction] ?? info.label}
    </Badge>
  );
}

const VERDICT: Record<Verdict, { label: string; color: string }> = {
  match: { label: 'Same', color: 'teal' },
  better: { label: 'Better', color: 'blue' },
  close: { label: 'Close', color: 'yellow' },
  worse: { label: 'Worse', color: 'orange' },
  differ: { label: 'Differs', color: 'red' },
  missing: { label: 'Unknown', color: 'gray' },
  info: { label: 'Not compared', color: 'gray' }
};

function detailRows(a: PartLabel | undefined, b: PartLabel | undefined): CompareRow[] {
  const numbers = (part: PartLabel | undefined) =>
    (part?.mpns ?? []).map((item) => `${item.manufacturer} ${item.mpn}`.trim()).join(', ') || null;

  const rows: [string, string | null, string | null][] = [
    ['Name', a?.name || null, b?.name || null],
    ['IPN', a?.ipn || null, b?.ipn || null],
    ['Description', a?.description || null, b?.description || null],
    ['Manufacturer part number', numbers(a), numbers(b)],
    ['Category', a?.category_name || null, b?.category_name || null]
  ];

  return rows
    .filter(([, left, right]) => left !== null || right !== null)
    .map(([label, left, right]) => ({
      key: `d:${label}`,
      label,
      level: 'info',
      a: left,
      b: right,
      derived: false,
      verdict: 'info'
    }));
}

/**
 * Two parts side by side: the attributes they are matched on with the result
 * for each, then every other parameter and the details of each part.
 */
export function CompareTable({
  rows,
  left,
  right,
  a,
  b
}: Readonly<{
  rows: CompareRow[] | undefined;
  left: string;
  right: string;
  a?: PartLabel;
  b?: PartLabel;
}>) {
  const compared = (rows ?? []).filter((row) => row.verdict !== 'info');
  const listed = [...detailRows(a, b), ...(rows ?? []).filter((row) => row.verdict === 'info')];

  const line = (row: CompareRow) => (
    <Table.Tr key={row.key}>
      <Table.Td>
        <Group gap={6} wrap='nowrap'>
          <Text size='sm' fw={row.level === 'critical' ? 600 : undefined} c={row.level === 'info' ? 'dimmed' : undefined}>
            {row.label}
          </Text>
          {row.derived && (
            <Tooltip label='Read from the name or description, not from a parameter'>
              <Badge size='xs' color='gray' variant='outline'>
                from text
              </Badge>
            </Tooltip>
          )}
        </Group>
      </Table.Td>
      <Table.Td>{row.a ?? <Text c='dimmed'>-</Text>}</Table.Td>
      <Table.Td>{row.b ?? <Text c='dimmed'>-</Text>}</Table.Td>
      <Table.Td style={{ textAlign: 'right' }}>
        {row.verdict !== 'info' && (
          <Badge size='sm' color={VERDICT[row.verdict].color} variant='light'>
            {VERDICT[row.verdict].label}
          </Badge>
        )}
      </Table.Td>
    </Table.Tr>
  );

  return (
    <Paper withBorder p='xs'>
      <Table verticalSpacing={4} horizontalSpacing='sm' fz='sm'>
        <Table.Thead>
          <Table.Tr>
            <Table.Th w='22%'>Matched on</Table.Th>
            <Table.Th w='34%'>{left}</Table.Th>
            <Table.Th w='34%'>{right}</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {compared.length === 0 && (
            <Table.Tr>
              <Table.Td colSpan={4}>
                <Text size='sm' c='dimmed'>
                  Neither part has a parameter the matching can use. Add the value, package
                  and ratings to both parts for a proper comparison.
                </Text>
              </Table.Td>
            </Table.Tr>
          )}
          {compared.map(line)}
        </Table.Tbody>
        {listed.length > 0 && (
          <>
            <Table.Thead>
              <Table.Tr>
                <Table.Th colSpan={4}>
                  <Text size='xs' c='dimmed' tt='uppercase' fw={600} pt='xs'>
                    Other fields (not used for matching)
                  </Text>
                </Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>{listed.map(line)}</Table.Tbody>
          </>
        )}
      </Table>
    </Paper>
  );
}

/** Button which shows or hides the comparison below a row */
export function ExpandButton({
  open,
  onClick
}: Readonly<{ open: boolean; onClick: () => void }>) {
  return (
    <ActionIcon
      variant='subtle'
      color='gray'
      size='sm'
      aria-label={open ? 'Hide the comparison' : 'Show the comparison'}
      onClick={onClick}
    >
      {open ? <IconChevronDown size={16} /> : <IconChevronRight size={16} />}
    </ActionIcon>
  );
}

export type LinkChoice = 'both' | 'forward' | 'reverse';

/**
 * Link a candidate, two-way or one-way. Both are always offered; the one the
 * comparison suggests is highlighted.
 *
 * 'forward' means the other part can replace this one.
 */
export function LinkActions({
  suggested,
  thisName,
  otherName,
  busy,
  onLink,
  onDismiss
}: Readonly<{
  suggested: Direction;
  thisName: string;
  otherName: string;
  busy: boolean;
  onLink: (choice: LinkChoice) => void;
  onDismiss?: () => void;
}>) {
  const choice: LinkChoice = suggested === 'none' ? 'forward' : suggested;
  const oneWay = choice !== 'both';

  const labels: Record<'forward' | 'reverse', string> = {
    forward: `${otherName} can replace ${thisName}`,
    reverse: `${thisName} can replace ${otherName}`
  };

  return (
    <Group gap={4} wrap='nowrap' justify='flex-end'>
      <Tooltip
        label={
          oneWay
            ? 'Link as interchangeable. The comparison suggests one-way: one part is better on a rating or tolerance.'
            : 'Link as interchangeable: suggested, as nothing in the comparison favours either part.'
        }
        multiline
        maw={320}
      >
        <Button
          size='compact-sm'
          variant={oneWay ? 'default' : 'light'}
          loading={busy}
          onClick={() => onLink('both')}
        >
          Two-way
        </Button>
      </Tooltip>
      <Menu position='bottom-end' withinPortal>
        <Menu.Target>
          <Button
            size='compact-sm'
            variant={oneWay ? 'light' : 'default'}
            rightSection={<IconChevronDown size={12} />}
            disabled={busy}
            aria-label='Link one-way'
          >
            One-way
          </Button>
        </Menu.Target>
        <Menu.Dropdown>
          <Menu.Label>Which way round?</Menu.Label>
          {(['forward', 'reverse'] as const).map((option) => (
            <Menu.Item key={option} onClick={() => onLink(option)}>
              {labels[option]}
              {option === choice ? ' (suggested)' : ''}
            </Menu.Item>
          ))}
        </Menu.Dropdown>
      </Menu>
      {onDismiss && (
        <Tooltip label='Not an alternative: hide it'>
          <ActionIcon
            variant='subtle'
            color='gray'
            aria-label='Not an alternative: hide it'
            disabled={busy}
            onClick={onDismiss}
          >
            <IconEyeOff size={16} />
          </ActionIcon>
        </Tooltip>
      )}
    </Group>
  );
}

export function SectionTitle({
  children,
  count,
  right
}: Readonly<{ children: ReactNode; count?: number; right?: ReactNode }>) {
  return (
    <Group justify='space-between' align='center'>
      <Group gap='xs' align='center'>
        <Text fw={600}>{children}</Text>
        {count !== undefined && (
          <Badge color='gray' variant='light' size='sm'>
            {count}
          </Badge>
        )}
      </Group>
      {right}
    </Group>
  );
}
