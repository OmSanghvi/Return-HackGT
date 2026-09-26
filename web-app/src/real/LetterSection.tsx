// Write-a-letter form + the project's letter list (Build Plan step 28).
// New file per the letters-backend-and-web skill's ownership rule --
// RealProjectPage.tsx only gets a one-line mount for this component.
//
// PDF pages: not rendered client-side here (pdfjs-dist isn't an existing
// dependency of web-app/, and the skill says to add no new one without
// checking first). This mirrors the sketch-card upload just above it in
// RealProjectPage, which already made the same call: image only, export a
// PDF page to PNG/JPEG first.
import { useCallback, useEffect, useState } from 'react';
import { Button, Field, Icon, StatusTag } from '../ui';
import { ApiError, createLetter, listLetters, openLetter } from '../api/client';
import type { Contributor, LetterView } from '../api/types';
import { useAuthedImage } from './useAuthedImage';

function LetterCard({
  projectId,
  letter,
  contributors,
  myContributorId,
  onChanged,
}: {
  projectId: string;
  letter: LetterView;
  contributors: Contributor[];
  myContributorId: string | null;
  onChanged: () => void;
}) {
  const image = useAuthedImage(letter.image_url);
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState('');

  const nameFor = (id: string) => contributors.find((c) => c.contributor_id === id)?.display_name ?? 'Someone';
  const recipientNames = letter.recipient_contributor_ids.map(nameFor).join(', ');
  const isRecipient = myContributorId != null && letter.recipient_contributor_ids.includes(myContributorId);
  const canOpen = letter.sealed && isRecipient;

  const doOpen = async () => {
    setOpening(true);
    setError('');
    try {
      await openLetter(projectId, letter.letter_id);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not open that letter.');
    } finally {
      setOpening(false);
    }
  };

  return (
    <div className="rt-card" style={{ position: 'relative', minHeight: 160, display: 'flex', flexDirection: 'column' }}>
      {image.url ? (
        <img className="rt-img" src={image.url} alt={`Letter for ${recipientNames}`} />
      ) : (
        <span className="rt-img rt-sky" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Icon name="mail" size={28} />
        </span>
      )}
      <span className="rt-card-top">
        <StatusTag status={letter.sealed ? 'waiting' : 'ready'} onImage>
          {letter.sealed ? 'Sealed' : 'Opened'}
        </StatusTag>
      </span>
      <span className="rt-card-foot">
        <span className="rt-card-title">
          {letter.sealed ? `Sealed letter for ${recipientNames}` : `Letter for ${recipientNames}`}
        </span>
      </span>
      {!letter.sealed && letter.note_text && (
        <p className="rt-field-hint" style={{ margin: '4px 0 0', fontStyle: 'italic' }}>
          &ldquo;{letter.note_text}&rdquo;
        </p>
      )}
      {canOpen && (
        <Button size="sm" variant="primary" loading={opening} onClick={doOpen} style={{ marginTop: 8 }}>
          Open
        </Button>
      )}
      {error && (
        <div className="rt-field-error">
          <Icon name="alert" size={16} />
          {error}
        </div>
      )}
    </div>
  );
}

export default function LetterSection({
  projectId,
  contributors,
  myContributorId,
}: {
  projectId: string;
  contributors: Contributor[];
  myContributorId: string | null;
}) {
  const [letters, setLetters] = useState<LetterView[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [recipients, setRecipients] = useState<Set<string>>(new Set());
  const [noteText, setNoteText] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    try {
      setLetters(await listLetters(projectId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not load letters.');
    }
  }, [projectId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const toggleRecipient = (id: string) =>
    setRecipients((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const send = async () => {
    if (!file || !myContributorId || recipients.size === 0) return;
    setSending(true);
    setError('');
    try {
      await createLetter(projectId, file, myContributorId, [...recipients], noteText);
      setFile(null);
      setRecipients(new Set());
      setNoteText('');
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not send that letter.');
    } finally {
      setSending(false);
    }
  };

  const otherContributors = contributors.filter((c) => c.contributor_id !== myContributorId);

  return (
    <div className="app-section">
      <h2 className="title" style={{ margin: 0 }}>
        Letters ({letters.length})
      </h2>

      {myContributorId ? (
        <div className="app-panel rt-glass-strong" style={{ margin: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
          <p className="rt-field-hint" style={{ margin: 0 }}>
            Upload a Notability page (PNG or JPEG -- export a PDF page to an image first), address it to
            whoever should open it, and add an optional note.
          </p>
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          {otherContributors.length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {otherContributors.map((c) => (
                <label key={c.contributor_id} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <input
                    type="checkbox"
                    checked={recipients.has(c.contributor_id)}
                    onChange={() => toggleRecipient(c.contributor_id)}
                  />
                  {c.display_name}
                </label>
              ))}
            </div>
          )}
          <Field
            label="Note (optional)"
            multiline
            value={noteText}
            onChange={(e) => setNoteText(e.target.value)}
            maxLength={2000}
          />
          <div className="app-actions" style={{ marginTop: 0 }}>
            <Button
              variant="primary"
              icon="mail"
              loading={sending}
              disabled={!file || recipients.size === 0}
              onClick={send}
            >
              Send letter
            </Button>
          </div>
        </div>
      ) : (
        <p className="rt-field-hint">Join this project as a contributor to write a letter.</p>
      )}

      {error && (
        <div className="rt-field-error" role="alert">
          <Icon name="alert" size={16} />
          {error}
        </div>
      )}

      <div className="app-grid">
        {letters.map((letter) => (
          <LetterCard
            key={letter.letter_id}
            projectId={projectId}
            letter={letter}
            contributors={contributors}
            myContributorId={myContributorId}
            onChanged={refresh}
          />
        ))}
        {letters.length === 0 && <p className="rt-field-hint">No letters yet.</p>}
      </div>
    </div>
  );
}
