import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Field, Icon } from '../ui';
import { RealShell } from './RealShell';
import { ApiError, createContributor, createProject } from '../api/client';
import { listKnownProjects, rememberProject } from './localProjects';
import { useAccount, accountLabel } from '../api/account';

export default function RealProjectsPage() {
  const navigate = useNavigate();
  const account = useAccount((s) => s.current);
  const known = listKnownProjects();

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState('');

  const [joinId, setJoinId] = useState('');
  const [joinCode, setJoinCode] = useState('');
  const [joinName, setJoinName] = useState('');
  const [joining, setJoining] = useState(false);
  const [joinError, setJoinError] = useState('');

  const create = async () => {
    if (!name.trim()) {
      setCreateError('Give the project a name.');
      return;
    }
    setCreating(true);
    setCreateError('');
    try {
      const project = await createProject({
        name: name.trim(),
        description: description.trim(),
        creator_display_name: accountLabel(account),
      });
      rememberProject({ project_id: project.project_id, name: project.name });
      navigate(`/projects/${project.project_id}`);
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : 'Could not create the project.');
    } finally {
      setCreating(false);
    }
  };

  const join = async () => {
    if (!joinId.trim()) {
      setJoinError('Enter the project id from the invite link.');
      return;
    }
    setJoining(true);
    setJoinError('');
    try {
      await createContributor(joinId.trim(), {
        display_name: joinName.trim() || accountLabel(account),
        invite_code: joinCode.trim() || null,
      });
      rememberProject({ project_id: joinId.trim(), name: joinId.trim() });
      navigate(`/projects/${joinId.trim()}`);
    } catch (err) {
      setJoinError(err instanceof ApiError ? err.message : 'Could not join that project.');
    } finally {
      setJoining(false);
    }
  };

  return (
    <RealShell>
      <div className="app-section">
        <h1 className="display-m" style={{ margin: '0 0 4px' }}>
          Projects
        </h1>
        <p className="body" style={{ margin: 0, color: 'var(--ink-muted)' }}>
          Acting as <strong>{accountLabel(account)}</strong> ({account}). Switch accounts from the header.
        </p>
      </div>

      {known.length > 0 && (
        <div className="app-section">
          <p className="rt-section-label">Known on this device</p>
          <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
            {known.map((p) => (
              <li key={p.project_id}>
                <button
                  type="button"
                  className="rt-btn rt-btn-secondary rt-btn-full"
                  style={{ justifyContent: 'flex-start' }}
                  onClick={() => navigate(`/projects/${p.project_id}`)}
                >
                  <Icon name="home" size={16} />
                  {p.name} <span style={{ color: 'var(--ink-faint)', marginLeft: 8 }}>{p.project_id}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="app-panel rt-glass-strong app-form" style={{ margin: 0 }}>
        <h2 className="title" style={{ margin: 0 }}>
          Create a project
        </h2>
        <Field label="Name" placeholder="The lake house" value={name} error={createError} onChange={(e) => setName(e.target.value)} />
        <Field label="Description (optional)" multiline rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
        <div className="app-actions">
          <Button variant="primary" loading={creating} onClick={create}>
            Create
          </Button>
        </div>
      </div>

      <div className="app-panel rt-glass-strong app-form" style={{ margin: 0 }}>
        <h2 className="title" style={{ margin: 0 }}>
          Join a project
        </h2>
        <Field label="Project id" placeholder="From the invite link" value={joinId} error={joinError} onChange={(e) => setJoinId(e.target.value)} />
        <Field label="Invite code" placeholder="From the invite link" value={joinCode} onChange={(e) => setJoinCode(e.target.value)} />
        <Field label="Display name (optional)" placeholder={accountLabel(account)} value={joinName} onChange={(e) => setJoinName(e.target.value)} />
        <div className="app-actions">
          <Button variant="secondary" loading={joining} onClick={join}>
            Join
          </Button>
        </div>
      </div>
    </RealShell>
  );
}
