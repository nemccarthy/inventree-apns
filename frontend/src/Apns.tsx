import type { InvenTreePluginContext } from '@inventreedb/ui';

import { ApnsPage } from './Page';
import { ApnsPartPanel } from './PartPanel';

/** The overview page, at /web/plugin/apns/overview */
export function renderApnsPage(context: InvenTreePluginContext) {
  return <ApnsPage context={context} />;
}

/** The Alternates panel on a part page */
export function renderApnsPartPanel(context: InvenTreePluginContext) {
  return <ApnsPartPanel context={context} />;
}
