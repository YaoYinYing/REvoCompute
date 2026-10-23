import { guidedTour } from '../../app/guided-tour';
import { parseResultManifest } from '../../api/result-api';
import type { ResultManifest, TaskStatus } from '../../api/result-types';
import { ResultWorkspace } from './ResultWorkspace';
import { mountLocalResultWorkspace as mountLocal } from './local-workspace';
import './results.css';

export { mountLocal as mountLocalResultWorkspace };

export async function mountResultWorkspace(root: HTMLElement): Promise<ResultWorkspace> {
  const workspace = new ResultWorkspace(root, async (host, options) => {
    const { MolecularViewer } = await import('../structure/MolecularViewer');
    return MolecularViewer.mount(host, options);
  });
  const loaded = await workspace.load();
  // An in-progress guided tour resumes on the surface it advanced to. The result
  // step is only reachable with a concrete task id, which the Dashboard records.
  guidedTour.resumeIfActive();
  // A result page that really loaded offers its own tour — this is the only kind
  // of page where a results flow makes sense, and it is offered only here.
  guidedTour.offer();
  return loaded;
}

/**
 * Mount the one Result Workspace against a validated demo replay scenario.
 *
 * The manifest is the bundle's own served ResultManifest v3, projected by the
 * Server; the artifact URLs in it are demo-scoped. The workspace therefore uses
 * its ordinary renderers, bounds, and teardown, and no second interpreter of the
 * result contract exists.
 */
export async function mountDemoResultWorkspace(root: HTMLElement, scenarioId: string, taskId: string): Promise<ResultWorkspace> {
  const workspace = new ResultWorkspace(root, async (host, options) => {
    const { MolecularViewer } = await import('../structure/MolecularViewer');
    return MolecularViewer.mount(host, options);
  }, null, {
    taskId,
    load: async (signal: AbortSignal): Promise<TaskStatus | ResultManifest> => {
      const response = await fetch(`/compute/api/demo/replays/${encodeURIComponent(scenarioId)}`, { credentials: 'same-origin', signal });
      const payload = await response.json().catch(() => ({})) as Record<string, unknown>;
      if (!response.ok) throw new Error(String(payload.error || `Request failed (HTTP ${response.status})`));
      return parseResultManifest(payload);
    },
  });
  return workspace.load();
}
