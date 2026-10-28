import { guidedTour } from '../../app/guided-tour';
import { CreateTask } from './CreateTask';
import './create-task.css';

export async function mountCreateTask(root: HTMLElement): Promise<CreateTask> {
  const view = new CreateTask(root);
  await view.mount();
  // An in-progress guided tour resumes on the surface it advanced to.
  guidedTour.resumeIfActive();
  // The route mount owns this view: a route change disposes it, including any
  // dialog it left in the top layer.
  return view;
}

