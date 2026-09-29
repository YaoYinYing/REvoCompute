import { ResultWorkspace } from './ResultWorkspace';
import './results.css';

export async function mountResultWorkspace(root: HTMLElement): Promise<ResultWorkspace> {
  const workspace = new ResultWorkspace(root, async (host, options) => {
    const { MolecularViewer } = await import('../structure/MolecularViewer');
    return MolecularViewer.mount(host, options);
  });
  return workspace.load();
}
