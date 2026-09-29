import { resultTaskId } from './app/result-route.js';
import { showStatusMessage } from './components/status-message.js';

const root = document.querySelector<HTMLElement>('#app');

if (!root) throw new Error('Missing frontend application root');

if (resultTaskId(window.location.pathname)) {
  import('./features/results/index.js')
    .then(({ mountResultWorkspace }) => mountResultWorkspace(root))
    .catch(error => {
      console.error('Unable to start the Result workspace', error);
      showStatusMessage(root, 'Unable to load this result.');
    });
} else {
  showStatusMessage(root, 'This frontend route is not available.');
}
