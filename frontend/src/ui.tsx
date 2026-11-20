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
  IconDots,
  IconEyeOff,
  IconLink
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

/** Part name, linked to the part page, with its IPN and first MPN */
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
  const details = [part.ipn, mpn ? `${mpn.manufacturer} ${mpn.mpn}`.trim() : ''].filter(Boolean);

  return (
    <Stack gap={0}>
      <Group gap={6} wrap='nowrap'>
        <AppLink context={context} to={partUrl(part.pk)} title={part.description}>
          {part.name}
        </AppLink>
        {part.active === false && (
          <Badge size='xs' color='gray' variant='light'>
            Inactive
          </Badge>
        )}
        {note}
      </Group>
      {details.length > 0 && (
        <Text size='xs' c='dimmed'>
          {details.join(' · ')}
        </Text>
      )}
    </Stack>
  );
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
    <Badge color={info.color} variant='light' leftSection={icon} style={{ flexShrink: 0 }}>
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
  missing: { label: 'Unknown', color: 'gray' }
};

/** The attribute by attribute comparison of two parts */
export function CompareTable({
  rows,
  left,
  right
}: Readonly<{ rows: CompareRow[] | undefined; left: string; right: string }>) {
  if (!rows || rows.length === 0) {
    return (
      <Text size='sm' c='dimmed'>
        Neither part has parameters to compare. Add parameters to both parts for a
        proper comparison.
      </Text>
    );
  }

  return (
    <Paper withBorder p='xs'>
      <Table verticalSpacing={4} horizontalSpacing='sm' fz='sm'>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Attribute</Table.Th>
            <Table.Th>{left}</Table.Th>
            <Table.Th>{right}</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((row) => (
            <Table.Tr key={row.key}>
              <Table.Td>
                <Group gap={6} wrap='nowrap'>
                  <Text size='sm' fw={row.level === 'critical' ? 600 : undefined}>
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
                <Badge size='sm' color={VERDICT[row.verdict].color} variant='light'>
                  {VERDICT[row.verdict].label}
                </Badge>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
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
 * Link a candidate: the suggested way as a button, the other ways in a menu.
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

  const labels: Record<LinkChoice, string> = {
    both: 'Two-way: interchangeable',
    forward: `One-way: ${otherName} can replace ${thisName}`,
    reverse: `One-way: ${thisName} can replace ${otherName}`
  };

  return (
    <Group gap={4} wrap='nowrap' justify='flex-end'>
      <Tooltip label={labels[choice]} multiline maw={320}>
        <Button
          size='compact-sm'
          variant='light'
          leftSection={<IconLink size={14} />}
          loading={busy}
          onClick={() => onLink(choice)}
        >
          {choice === 'both' ? 'Link two-way' : 'Link one-way'}
        </Button>
      </Tooltip>
      <Menu position='bottom-end' withinPortal>
        <Menu.Target>
          <ActionIcon variant='subtle' color='gray' aria-label='More ways to link' disabled={busy}>
            <IconDots size={16} />
          </ActionIcon>
        </Menu.Target>
        <Menu.Dropdown>
          <Menu.Label>Link as</Menu.Label>
          {(['both', 'forward', 'reverse'] as LinkChoice[]).map((option) => (
            <Menu.Item key={option} onClick={() => onLink(option)}>
              {labels[option]}
              {option === choice ? ' (suggested)' : ''}
            </Menu.Item>
          ))}
          {onDismiss && (
            <>
              <Menu.Divider />
              <Menu.Item leftSection={<IconEyeOff size={14} />} onClick={onDismiss}>
                Not an alternate: hide it
              </Menu.Item>
            </>
          )}
        </Menu.Dropdown>
      </Menu>
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
