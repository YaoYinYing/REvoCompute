import { MolecularViewer } from '../structure/MolecularViewer';
import { ResultWorkspace } from './ResultWorkspace';
import './results.css';

export async function mountResultWorkspace(root: HTMLElement): Promise<ResultWorkspace> {
  const workspace = new ResultWorkspace(root, (host, options) => MolecularViewer.mount(host, options));
  return workspace.load();
}
