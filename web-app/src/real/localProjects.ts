// The backend has no "list my projects" route (main.py only has
// create/read-by-id), so the web app remembers which projects it has
// created or joined in this browser. This is a convenience index only --
// the backend project record stays the source of truth for everything else,
// and this list can be safely lost (a project is still reachable by pasting
// its id into "Join a project").
const KEY = 'sketchscape-real-known-projects';

export interface KnownProject {
  project_id: string;
  name: string;
  /** Kept by the creator's browser so the other account on this device can join. */
  invite_code?: string;
  creator?: string;
  /** Accounts that declined the invitation (hidden for them only). */
  declinedBy?: string[];
  /** Owner chose "Start without": build with whoever is in. */
  forced?: boolean;
  /** Owner's "What should we rebuild?" list, reused for everyone's photos. */
  objects?: string[];
}

export function listKnownProjects(): KnownProject[] {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as KnownProject[]) : [];
  } catch {
    return [];
  }
}

export function rememberProject(project: KnownProject): void {
  try {
    const all = listKnownProjects();
    const prev = all.find((p) => p.project_id === project.project_id);
    const known = all.filter((p) => p.project_id !== project.project_id);
    localStorage.setItem(KEY, JSON.stringify([{ ...prev, ...project }, ...known].slice(0, 50)));
  } catch {
    // localStorage unavailable (private mode, quota) -- the project is still reachable by id.
  }
}

export function updateKnownProject(projectId: string, patch: Partial<KnownProject>): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(listKnownProjects().map((p) => (p.project_id === projectId ? { ...p, ...patch } : p))));
  } catch {
    // Best-effort, same as rememberProject.
  }
}

export function forgetProject(projectId: string): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(listKnownProjects().filter((p) => p.project_id !== projectId)));
  } catch {
    // Ignore -- best-effort cleanup.
  }
}
