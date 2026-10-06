import { guidedTour } from '../../app/guided-tour';
import { ResultWorkspace } from './ResultWorkspace';
import './results.css';

export async function mountResultWorkspace(root: HTMLElement): Promise<ResultWorkspace> {
  const workspace = new ResultWorkspace(root, async (host, options) => {
    const { MolecularViewer } = await import('../structure/MolecularViewer');
    return MolecularViewer.mount(host, options);
  });
  const loaded = await workspace.load();
  // An in-progress guided tour resumes on the surface it advanced to. The result
  // step is only reachable with a concrete task id, which the Dashboard records.
  guidedTour.resumeIfActive();
  return loaded;
}
