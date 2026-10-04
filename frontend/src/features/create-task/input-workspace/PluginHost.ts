import type { WorkspaceCapability, WorkspaceDescriptor, WorkspaceSummary, WorkspaceValues } from '../types';
import type { WorkspaceContext, WorkspacePlugin, WorkspacePluginInstance, WorkspacePluginModule, WorkspacePluginServices } from './plugin-contract';
import { isWorkspacePlugin } from './plugin-contract';

interface MountedPlugin {
  definition: WorkspaceCapability;
  plugin: WorkspacePlugin;
  instance: WorkspacePluginInstance;
  target: HTMLElement;
}

type ModuleLoader = (url: string) => Promise<unknown>;

const moduleLoader: ModuleLoader = (url) => import(/* @vite-ignore */ url);

export class PluginHost {
  private readonly plugins = new Map<string, WorkspacePlugin>();
  private readonly mounted: MountedPlugin[] = [];
  private readonly styles: HTMLLinkElement[] = [];
  private loadFaults: string[] = [];
  private faults: string[] = [];
  private disposed = false;

  constructor(
    builtins: WorkspacePlugin[],
    private readonly services: WorkspacePluginServices,
    private readonly loadModule: ModuleLoader = moduleLoader,
  ) {
    builtins.forEach(plugin => this.register(plugin));
  }

  private register(plugin: WorkspacePlugin): void {
    if (this.plugins.has(plugin.id)) throw new Error(`Duplicate workspace plugin: ${plugin.id}`);
    this.plugins.set(plugin.id, plugin);
  }

  async load(descriptors: WorkspaceDescriptor[]): Promise<void> {
    for (const descriptor of descriptors) {
      try {
        const loaded = await this.loadModule(descriptor.module.url) as Partial<WorkspacePluginModule>;
        if (this.disposed) return;
        if (!isWorkspacePlugin(loaded.default) || loaded.default.id !== descriptor.id) {
          throw new Error('did not export its declared default module');
        }
        this.register(loaded.default);
        if (descriptor.global_id !== descriptor.id) this.plugins.set(descriptor.global_id, loaded.default);
        descriptor.stylesheets.forEach(stylesheet => {
          const link = document.createElement('link');
          link.rel = 'stylesheet'; link.href = stylesheet.url; link.type = stylesheet.media_type;
          link.dataset.workspacePlugin = descriptor.global_id;
          document.head.append(link); this.styles.push(link);
        });
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        this.loadFaults.push(`${descriptor.global_id}: ${message}`);
      }
    }
  }

  mount(definitions: WorkspaceCapability[], context: WorkspaceContext, createTarget: (definition: WorkspaceCapability) => HTMLElement): void {
    this.faults = [...this.loadFaults];
    definitions.forEach(definition => {
      const plugin = this.plugins.get(definition.plugin);
      if (!plugin) { this.faults.push(`${definition.plugin}: unsupported component`); return; }
      const target = createTarget(definition);
      try {
        this.mounted.push({ definition, plugin, target, instance: plugin.mount(target, definition, context, this.services) || {} });
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        this.faults.push(`${definition.plugin}: ${message}`);
        target.replaceChildren(Object.assign(document.createElement('p'), { className: 'ct-component-error', textContent: `This component could not load: ${message}` }));
      }
    });
  }

  collect(): WorkspaceValues {
    const result: WorkspaceValues = {};
    this.mounted.forEach(item => {
      if (!item.instance.readValue) return;
      try { result[item.definition.id] = item.instance.readValue(); }
      catch (error) { this.faults.push(`${item.plugin.id}: ${error instanceof Error ? error.message : String(error)}`); }
    });
    return result;
  }

  summaries(): WorkspaceSummary[] {
    const result: WorkspaceSummary[] = [];
    this.mounted.forEach(item => {
      if (!item.instance.summarize) return;
      try {
        const value = item.instance.summarize();
        if (Array.isArray(value)) result.push(...value); else if (value) result.push(value);
      } catch (error) { this.faults.push(`${item.plugin.id}: ${error instanceof Error ? error.message : String(error)}`); }
    });
    return result;
  }

  validate(): string[] {
    const errors = [...this.faults];
    this.mounted.forEach(item => {
      if (!item.instance.validate) return;
      try {
        const value = item.instance.validate();
        if (Array.isArray(value)) errors.push(...value); else if (value) errors.push(value);
      } catch (error) { errors.push(`${item.plugin.id}: ${error instanceof Error ? error.message : String(error)}`); }
    });
    return [...new Set(errors)];
  }

  refresh(): void {
    this.mounted.forEach(item => {
      try {
        void Promise.resolve(item.instance.refresh?.()).catch(error => {
          this.faults.push(`${item.plugin.id}: ${error instanceof Error ? error.message : String(error)}`);
        });
      } catch (error) {
        this.faults.push(`${item.plugin.id}: ${error instanceof Error ? error.message : String(error)}`);
      }
    });
  }

  destroy(): void {
    this.disposed = true;
    this.mounted.splice(0).reverse().forEach(item => { try { item.instance.destroy?.(); } catch { /* Isolate plugin teardown. */ } });
    this.styles.splice(0).forEach(link => link.remove());
    this.loadFaults = [];
    this.faults = [];
  }
}
