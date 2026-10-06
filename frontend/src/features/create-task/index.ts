import { guidedTour } from '../../app/guided-tour';
import { CreateTask } from './CreateTask';
import './create-task.css';

export async function mountCreateTask(root: HTMLElement): Promise<void> {
  await new CreateTask(root).mount();
  // An in-progress guided tour resumes on the surface it advanced to.
  guidedTour.resumeIfActive();
}

