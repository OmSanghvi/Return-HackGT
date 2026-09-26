import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { Button, Field, Icon, StatusTag } from '../ui';
import { RealShell } from './RealShell';
import {
  ApiError,
  createSelections,
  createSketchCard,
  createUpload,
  deleteSelection,
  detectUploadObjects,
  generateSelectedObjects,
  getProject,
  getUpload,
  listContributors,
  listProjectAssets,
  refineSelection,
  updateProject,
} from '../api/client';
import { pollProjectJobs, type JobPollHandle } from '../api/polling';
import type { Contributor, ProjectAsset, ProjectRecord, UploadSelection } from '../api/types';
import { rememberProject } from './localProjects';
import { useAuthedImage } from './useAuthedImage';
import { useAccount } from '../api/account';
import LetterSection from './LetterSection';

interface UploadEntry {
  upload_id: string;
  image_url: string;
  width: number;
  height: number;
  selections: UploadSelection[];
}

const newSelectionId = () => (crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2));

function statusTagFor(status: UploadSelection['status']) {
  if (status === 'segmented') return <StatusTag status="ready">Found</StatusTag>;
  if (status === 'failed') return <StatusTag status="failed">Needs a fix</StatusTag>;
  if (status === 'generated') return <StatusTag status="shared">Making 3D</StatusTag>;
  return <StatusTag status="waiting">Looking...</StatusTag>;
}

function SelectionRow({
  projectId,
  uploadId,
  selection,
  checked,
  onToggleChecked,
  onChanged,
}: {
  projectId: string;
  uploadId: string;
  selection: UploadSelection;
  checked: boolean;
  onToggleChecked: () => void;
  onChanged: () => void;
}) {
  const [refineText, setRefineText] = useState('');
  const [busy, setBusy] = useState(false);
  const mask = useAuthedImage(selection.mask_preview_url ? `/v1/projects/${projectId}/uploads/${uploadId}/selections/${selection.selection_id}/mask` : null);

  const refine = async () => {
    if (!refineText.trim()) return;
    setBusy(true);
    try {
      await refineSelection(projectId, uploadId, selection.selection_id, refineText.trim());
      setRefineText('');
      onChanged();
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    try {
      await deleteSelection(projectId, uploadId, selection.selection_id);
      onChanged();
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className="rt-chip" style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 6, height: 'auto', padding: 'var(--space-2) var(--space-3)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%' }}>
        {selection.status === 'segmented' && (
          <input type="checkbox" checked={checked} onChange={onToggleChecked} aria-label={`Include "${selection.prompt.text}" in Make 3D`} />
        )}
        <strong>{selection.prompt.text}</strong>
        {statusTagFor(selection.status)}
        {selection.score != null && <span className="rt-field-hint">score {selection.score.toFixed(2)}</span>}
        <button type="button" className="rt-chip-x" aria-label={`Delete ${selection.prompt.text}`} onClick={remove} disabled={busy}>
          <Icon name="x" size={12} strokeWidth={2.5} />
        </button>
      </div>
      {mask.url && <img src={mask.url} alt={`Mask preview for ${selection.prompt.text}`} style={{ width: 96, height: 96, objectFit: 'cover', borderRadius: 8 }} />}
      {selection.memory_text && <p className="rt-field-hint" style={{ margin: 0, fontStyle: 'italic' }}>&ldquo;{selection.memory_text}&rdquo;</p>}
      <div style={{ display: 'flex', gap: 6, width: '100%' }}>
        <input
          className="rt-input"
          placeholder="Not it? Type a more specific name"
          value={refineText}
          onChange={(e) => setRefineText(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && refine()}
          style={{ flex: 1 }}
        />
        <Button size="sm" variant="ghost" loading={busy} onClick={refine}>
          Refine
        </Button>
      </div>
    </li>
  );
}

function UploadCard({
  projectId,
  upload,
  onChanged,
}: {
  projectId: string;
  upload: UploadEntry;
  onChanged: (uploadId: string) => void;
}) {
  const [pendingNames, setPendingNames] = useState<{ text: string; memory: string }[]>([]);
  const [draft, setDraft] = useState('');
  const [draftMemory, setDraftMemory] = useState('');
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [suggesting, setSuggesting] = useState(false);
  const [error, setError] = useState('');
  const image = useAuthedImage(upload.image_url);

  const addDraft = () => {
    const text = draft.trim().slice(0, 100);
    if (!text) return;
    if (upload.selections.length + pendingNames.length >= 8) {
      setError('A photo may have at most 8 selected objects.');
      return;
    }
    setPendingNames((v) => [...v, { text, memory: draftMemory.trim().slice(0, 1000) }]);
    setDraft('');
    setDraftMemory('');
    setError('');
  };

  const findObjects = async () => {
    if (pendingNames.length === 0) return;
    setBusy(true);
    setError('');
    try {
      await createSelections(
        projectId,
        upload.upload_id,
        pendingNames.map((p) => ({
          selection_id: newSelectionId(),
          prompt: { text: p.text },
          memory_text: p.memory || undefined,
        })),
      );
      setPendingNames([]);
      onChanged(upload.upload_id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not submit those objects.');
    } finally {
      setBusy(false);
    }
  };

  const suggestObject = async () => {
    setSuggesting(true);
    setError('');
    try {
      await detectUploadObjects(projectId, upload.upload_id);
      onChanged(upload.upload_id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not suggest an object.');
    } finally {
      setSuggesting(false);
    }
  };

  const makeThreeD = async () => {
    const ids = [...checked];
    if (ids.length === 0) return;
    setBusy(true);
    setError('');
    try {
      await generateSelectedObjects(projectId, upload.upload_id, ids);
      setChecked(new Set());
      onChanged(upload.upload_id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not start Make 3D.');
    } finally {
      setBusy(false);
    }
  };

  const toggle = (id: string) =>
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="app-panel rt-glass-strong" style={{ margin: 0 }}>
      <div style={{ display: 'flex', gap: 'var(--space-4)', flexWrap: 'wrap' }}>
        {image.url && <img src={image.url} alt="Uploaded photo" style={{ width: 180, height: 180, objectFit: 'cover', borderRadius: 12 }} />}
        <div style={{ flex: 1, minWidth: 240, display: 'flex', flexDirection: 'column', gap: 8 }}>
          <p className="rt-field-hint" style={{ margin: 0 }}>
            Type a name for each object you want in 3D (e.g. "blue vase"), add an optional memory or reason, then find them.
          </p>
          <div style={{ display: 'flex', gap: 6 }}>
            <input
              className="rt-input"
              placeholder="Object name"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && addDraft()}
              style={{ flex: 1 }}
            />
            <input
              className="rt-input"
              placeholder="Why this matters (optional)"
              value={draftMemory}
              onChange={(e) => setDraftMemory(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && addDraft()}
              style={{ flex: 1 }}
            />
            <Button size="sm" variant="secondary" icon="plus" onClick={addDraft}>
              Add
            </Button>
          </div>
          <div className="app-actions" style={{ marginTop: 0 }}>
            <Button size="sm" variant="ghost" loading={suggesting} onClick={suggestObject}>
              Suggest an object
            </Button>
          </div>
          {pendingNames.length > 0 && (
            <ul className="rt-chips" style={{ margin: 0 }}>
              {pendingNames.map((n, i) => (
                <li key={i} className="rt-chip">
                  {n.text}
                  {n.memory && <span className="rt-field-hint"> — &ldquo;{n.memory}&rdquo;</span>}
                  <button type="button" className="rt-chip-x" aria-label={`Remove ${n.text}`} onClick={() => setPendingNames((v) => v.filter((_, j) => j !== i))}>
                    <Icon name="x" size={12} strokeWidth={2.5} />
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="app-actions" style={{ marginTop: 0 }}>
            <Button size="sm" variant="primary" loading={busy} disabled={pendingNames.length === 0} onClick={findObjects}>
              Find these objects
            </Button>
            <Button
              size="sm"
              variant="secondary"
              loading={busy}
              disabled={checked.size === 0}
              onClick={makeThreeD}
            >
              Make 3D ({checked.size})
            </Button>
          </div>
          {error && (
            <div className="rt-field-error">
              <Icon name="alert" size={16} />
              {error}
            </div>
          )}
        </div>
      </div>
      {upload.selections.length > 0 && (
        <ul className="rt-chips" style={{ margin: 0, flexWrap: 'wrap', listStyle: 'none', padding: 0, display: 'flex', gap: 8 }}>
          {upload.selections.map((s) => (
            <SelectionRow
              key={s.selection_id}
              projectId={projectId}
              uploadId={upload.upload_id}
              selection={s}
              checked={checked.has(s.selection_id)}
              onToggleChecked={() => toggle(s.selection_id)}
              onChanged={() => onChanged(upload.upload_id)}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function AssetCard({ asset }: { asset: ProjectAsset }) {
  const previewPath = asset.preview_url ?? asset.artifact_url;
  const preview = useAuthedImage(previewPath && previewPath.startsWith('/') ? previewPath : null);
  const status = asset.status === 'ready' ? 'ready' : asset.status === 'failed' ? 'failed' : 'developing';
  return (
    <div className="rt-card" style={{ position: 'relative', minHeight: 160 }}>
      {preview.url ? <img className="rt-img" src={preview.url} alt={asset.label} /> : <span className="rt-img rt-sky" />}
      <span className="rt-card-foot">
        <span className="rt-card-title">{asset.label}</span>
      </span>
      <span className="rt-card-top">
        <StatusTag status={status} onImage>
          {asset.kind === 'sketch_card' ? 'Sketch' : undefined}
        </StatusTag>
      </span>
    </div>
  );
}

export default function RealProjectPage() {
  const { id } = useParams<{ id: string }>();
  const account = useAccount((s) => s.current);
  const [project, setProject] = useState<ProjectRecord | null>(null);
  const [contributors, setContributors] = useState<Contributor[]>([]);
  const [assets, setAssets] = useState<ProjectAsset[]>([]);
  const [uploads, setUploads] = useState<Record<string, UploadEntry>>({});
  const [uploadOrder, setUploadOrder] = useState<string[]>([]);
  const [error, setError] = useState('');
  const [roomPrompt, setRoomPrompt] = useState('');
  const [savingPrompt, setSavingPrompt] = useState(false);
  const [uploadingCount, setUploadingCount] = useState(0);
  const [activeJobCount, setActiveJobCount] = useState(0);
  const [sketchLabel, setSketchLabel] = useState('');
  const fileInput = useRef<HTMLInputElement>(null);
  const sketchInput = useRef<HTMLInputElement>(null);
  const pollRef = useRef<JobPollHandle | null>(null);

  const refreshUpload = useCallback(
    async (uploadId: string) => {
      if (!id) return;
      const rec = await getUpload(id, uploadId);
      setUploads((prev) => ({
        ...prev,
        [uploadId]: { upload_id: rec.upload_id, image_url: `/v1/projects/${id}/uploads/${uploadId}/image`, width: rec.width, height: rec.height, selections: rec.selections },
      }));
    },
    [id],
  );

  const refreshAssets = useCallback(async () => {
    if (!id) return;
    setAssets(await listProjectAssets(id));
  }, [id]);

  const ensurePolling = useCallback(() => {
    if (!id || pollRef.current) return;
    pollRef.current = pollProjectJobs(id, {
      onActive: (jobs) => setActiveJobCount(jobs.length),
      onSettled: (jobs) => {
        // Refetch only the uploads/assets a settled job touched.
        const uploadIds = new Set(jobs.map((j) => j.upload_id).filter((v): v is string => Boolean(v)));
        uploadIds.forEach((uid) => void refreshUpload(uid));
        if (jobs.some((j) => j.kind === 'reconstruct')) void refreshAssets();
      },
      onIdle: () => {
        setActiveJobCount(0);
        Object.keys(uploads).forEach((uid) => void refreshUpload(uid));
        void refreshAssets();
        pollRef.current = null;
      },
    });
  }, [id, refreshAssets, refreshUpload, uploads]);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const [proj, contribs, assetList] = await Promise.all([getProject(id), listContributors(id), listProjectAssets(id)]);
      setProject(proj);
      setContributors(contribs);
      setAssets(assetList);
      setRoomPrompt(proj.room_prompt ?? '');
      rememberProject({ project_id: proj.project_id, name: proj.name });
      setError('');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not load this project.');
    }
  }, [id]);

  useEffect(() => {
    void load();
    return () => {
      pollRef.current?.stop();
      pollRef.current = null;
    };
    // Reload when the account switches too, since visibility (invite_code) depends on membership.
  }, [load, account]);

  const onFiles = async (files: FileList | null) => {
    if (!id || !files) return;
    for (const file of Array.from(files)) {
      setUploadingCount((n) => n + 1);
      try {
        const res = await createUpload(id, file);
        setUploads((prev) => ({ ...prev, [res.upload_id]: { upload_id: res.upload_id, image_url: res.image_url, width: res.width, height: res.height, selections: [] } }));
        setUploadOrder((prev) => [res.upload_id, ...prev]);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : `Could not upload ${file.name}.`);
      } finally {
        setUploadingCount((n) => n - 1);
      }
    }
  };

  const onChanged = (uploadId: string) => {
    void refreshUpload(uploadId);
    ensurePolling();
  };

  const saveRoomPrompt = async () => {
    if (!id) return;
    setSavingPrompt(true);
    try {
      const proj = await updateProject(id, { room_prompt: roomPrompt.trim() || null });
      setProject(proj);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save the room prompt.');
    } finally {
      setSavingPrompt(false);
    }
  };

  const uploadSketch = async (file: File) => {
    if (!id) return;
    try {
      const asset = await createSketchCard(id, file, sketchLabel.trim());
      setAssets((prev) => [asset, ...prev]);
      setSketchLabel('');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not upload that sketch.');
    }
  };

  if (!id) return null;

  return (
    <RealShell>
      {error && (
        <div className="rt-field-error" role="alert">
          <Icon name="alert" size={16} />
          {error}
        </div>
      )}
      {!project ? (
        <p>Loading...</p>
      ) : (
        <>
          <div className="app-section">
            <h1 className="display-m" style={{ margin: '0 0 4px' }}>
              {project.name}
            </h1>
            {project.description && (
              <p className="body" style={{ margin: 0, color: 'var(--ink-muted)' }}>
                {project.description}
              </p>
            )}
          </div>

          <div className="app-panel rt-glass-strong" style={{ margin: 0, display: 'flex', flexWrap: 'wrap', gap: 'var(--space-5)' }}>
            <div style={{ flex: 1, minWidth: 220 }}>
              <p className="rt-section-label">Contributors ({contributors.length})</p>
              <ul style={{ margin: 0, padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 4 }}>
                {contributors.map((c) => (
                  <li key={c.contributor_id}>
                    {c.display_name}
                    {c.clerk_user_id === account && <span className="rt-field-hint"> (you)</span>}
                  </li>
                ))}
              </ul>
            </div>
            {project.invite_code && (
              <div style={{ flex: 1, minWidth: 220 }}>
                <p className="rt-section-label">Invite</p>
                <p style={{ margin: 0, fontSize: 13 }}>
                  Project id: <code>{project.project_id}</code>
                </p>
                <p style={{ margin: 0, fontSize: 13 }}>
                  Code: <code>{project.invite_code}</code>
                </p>
              </div>
            )}
            <div style={{ flex: 1, minWidth: 220 }}>
              <p className="rt-section-label">
                Room prompt {activeJobCount > 0 && <span className="rt-field-hint">· {activeJobCount} job(s) running</span>}
              </p>
              <div style={{ display: 'flex', gap: 6 }}>
                <input className="rt-input" style={{ flex: 1 }} value={roomPrompt} maxLength={300} onChange={(e) => setRoomPrompt(e.target.value)} placeholder="Describe the room you want" />
                <Button size="sm" variant="secondary" loading={savingPrompt} onClick={saveRoomPrompt}>
                  Save
                </Button>
              </div>
            </div>
          </div>

          <div className="app-section">
            <div className="app-actions" style={{ marginTop: 0 }}>
              <h2 className="title" style={{ margin: 0 }}>
                Photos
              </h2>
              <Button variant="primary" icon="upload" loading={uploadingCount > 0} onClick={() => fileInput.current?.click()}>
                Add photos
              </Button>
              <input ref={fileInput} type="file" accept="image/jpeg,image/png,image/webp" multiple hidden onChange={(e) => { void onFiles(e.target.files); e.target.value = ''; }} />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
              {uploadOrder.map((uid) => uploads[uid] && <UploadCard key={uid} projectId={id} upload={uploads[uid]} onChanged={onChanged} />)}
              {uploadOrder.length === 0 && <p className="rt-field-hint">No photos yet. Add one to start.</p>}
            </div>
          </div>

          <div className="app-section">
            <h2 className="title" style={{ margin: 0 }}>
              Notability sketch (flat card)
            </h2>
            <p className="rt-field-hint" style={{ marginTop: 4 }}>
              PNG or JPEG only for now -- export a PDF page as an image first.
            </p>
            <div style={{ display: 'flex', gap: 6, alignItems: 'flex-end' }}>
              <Field label="Label (optional)" placeholder="Grandma's letter" value={sketchLabel} onChange={(e) => setSketchLabel(e.target.value)} />
              <Button variant="secondary" icon="upload" onClick={() => sketchInput.current?.click()}>
                Upload sketch
              </Button>
              <input
                ref={sketchInput}
                type="file"
                accept="image/png,image/jpeg"
                hidden
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) void uploadSketch(file);
                  e.target.value = '';
                }}
              />
            </div>
          </div>

          <LetterSection
            projectId={id}
            contributors={contributors}
            myContributorId={contributors.find((c) => c.clerk_user_id === account)?.contributor_id ?? null}
          />

          <div className="app-section">
            <h2 className="title" style={{ margin: 0 }}>
              Objects ({assets.length})
            </h2>
            <div className="app-grid">
              {assets.map((a) => (
                <AssetCard key={a.asset_id} asset={a} />
              ))}
              {assets.length === 0 && <p className="rt-field-hint">Nothing generated yet.</p>}
            </div>
          </div>
        </>
      )}
    </RealShell>
  );
}
