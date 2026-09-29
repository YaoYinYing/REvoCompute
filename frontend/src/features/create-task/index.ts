import { CreateTask } from './CreateTask';
import './create-task.css';

export async function mountCreateTask(root: HTMLElement): Promise<void> {
  await new CreateTask(root).mount();
}

