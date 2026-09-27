// Write-a-letter form + the project's letter list (Build Plan step 28).
// New file per the letters-backend-and-web skill's ownership rule --
// RealProjectPage.tsx only gets a one-line mount for this component.
//
// A letter is typed here and drawn onto a paper page in the browser (the
// page is what the headset unfolds), or a Notability page image is attached
// instead (PNG/JPEG/WebP -- pdfjs-dist isn't a dependency, so export a PDF
// page to an image first). Sealed until a recipient opens it: a recipient
// sees only the envelope until then, the author always sees their own page.
import { useCallback, useEffect, useState } from 'react';
import { Button, Field, Icon, StatusTag } from '../ui';
import { ApiError, createLetter, listLetters, openLetter } from '../api/client';
import type { Contributor, LetterView } from '../api/types';
import { useAccount } from '../api/account';
import { useAuthedImage } from './useAuthedImage';

const LETTER_MAX = 2000; // backend note_text limit
const POLL_MS = 8000; // the other account's letters and opens show up without a reload

/** Wrap `text` to `maxWidth` on the canvas, keeping the writer's own line breaks. */
function wrap(g: CanvasRenderingContext2D, text: string, maxWidth: number): string[] {
  const lines: string[] = [];
  for (const para of text.split(/\r?\n/)) {
    if (!para.trim()) {
      lines.push('');
      continue;
    }
    let line = '';
    for (const word of para.split(/\s+/).filter(Boolean)) {
      const next = line ? `${line} ${word}` : word;
      if (g.measureText(next).width <= maxWidth || !line) line = next;
      else {
        lines.push(line);
        line = word;
      }
    }
    if (line) lines.push(line);
  }
  return lines;
}

/**
 * Draw a typed letter onto a cream, lightly ruled sheet (A4 at 150 dpi) and
 * return it as a PNG page for the letters API. Long letters shrink the type
 * to fit one page.
 */
async function renderLetterPage(text: string, from: string, to: string): Promise<File> {
  const W = 1240;
  const H = 1754;
  const canvas = document.createElement('canvas');
  canvas.width = W;
  canvas.height = H;
  const g = canvas.getContext('2d');
  if (!g) throw new Error('This browser cannot draw the letter page.');
  const paper = g.createLinearGradient(0, 0, W, H);
  paper.addColorStop(0, '#fbf7ee');
  paper.addColorStop(1, '#f2e9d6');
  g.fillStyle = paper;
  g.fillRect(0, 0, W, H);

  try {
    await Promise.all([document.fonts.load('italic 48px "Cormorant"'), document.fonts.load('600 48px "Cormorant"')]);
  } catch {
    // Falls back to Georgia; the page still reads fine.
  }
  const margin = 140;
  const body = text.trim();
  let size = 64;
  let lines: string[] = [];
  for (; size >= 28; size -= 2) {
    g.font = `italic ${size}px Cormorant, Georgia, serif`;
    lines = wrap(g, body, W - 2 * margin);
    if (260 + lines.length * size * 1.45 < H - 260) break;
  }
  const lineH = Math.round(size * 1.45);

  // Faint rules under each line of writing, like good stationery.
  g.strokeStyle = 'rgba(64, 96, 150, 0.14)';
  g.lineWidth = 2;
  for (let y = 250 + lineH; y < H - 160; y += lineH) {
    g.beginPath();
    g.moveTo(margin - 30, y + 10);
    g.lineTo(W - margin + 30, y + 10);
    g.stroke();
  }

  g.fillStyle = '#2d2b3d';
  g.font = `600 ${Math.round(size * 1.05)}px Cormorant, Georgia, serif`;
  g.fillText(`Dear ${to},`, margin, 200);
  g.font = `italic ${size}px Cormorant, Georgia, serif`;
  lines.forEach((line, i) => g.fillText(line, margin, 250 + (i + 1) * lineH));
  g.font = `italic ${Math.round(size * 1.05)}px Cormorant, Georgia, serif`;
  const sign = `With love, ${from}`;
  g.fillText(sign, W - margin - g.measureText(sign).width, Math.min(H - 110, 250 + (lines.length + 2) * lineH));

  const blob = await new Promise<Blob>((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('Could not draw the letter page.'))), 'image/png'),
  );
  return new File([blob], 'letter.png', { type: 'image/png' });
}

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
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState('');

  const nameFor = (id: string) => contributors.find((c) => c.contributor_id === id)?.display_name ?? 'Someone';
  const recipientNames = letter.recipient_contributor_ids.map(nameFor).join(', ');
  const author = nameFor(letter.author_contributor_id);
  const isAuthor = myContributorId != null && letter.author_contributor_id === myContributorId;
  const isRecipient = myContributorId != null && letter.recipient_contributor_ids.includes(myContributorId);
  // Sealed to a recipient means sealed: the envelope, not the page, until they open it.
  const canOpen = letter.sealed && isRecipient && !isAuthor;
  const showPage = !canOpen && !!letter.image_url;
  const image = useAuthedImage(showPage ? letter.image_url : null);
  const openers = letter.opened_by.map(nameFor).join(', ');

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

  const status = letter.sealed
    ? isAuthor
      ? `Sealed · waiting for ${recipientNames} to open it`
      : isRecipient
        ? 'Sealed · only you can open it'
        : `Sealed · for ${recipientNames}`
    : `Opened${openers ? ` by ${openers}` : ''}`;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {/* The page (or, while it's sealed to you, the envelope) is the card; words about it sit underneath. */}
      <div className="rt-card" style={{ position: 'relative', aspectRatio: '3 / 4', minHeight: 0 }}>
        {image.url ? (
          <img className="rt-img" style={{ objectPosition: 'top' }} src={image.url} alt={`Letter from ${author} to ${recipientNames}`} />
        ) : (
          <span className="rt-img rt-sky" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Icon name={letter.sealed ? 'lock' : 'mail'} size={32} />
          </span>
        )}
        <span className="rt-scrim-bottom" />
        <span className="rt-card-top">
          <StatusTag status={letter.sealed ? 'waiting' : 'ready'} onImage>
            {letter.sealed ? 'Sealed' : 'Opened'}
          </StatusTag>
        </span>
        <span className="rt-card-foot">
          <span className="rt-card-title">{`From ${author} to ${recipientNames}`}</span>
        </span>
      </div>
      <p className="rt-field-hint" style={{ margin: 0 }}>
        {status}
      </p>
      {!canOpen && letter.note_text && (
        <p
          className="rt-field-hint"
          style={{ margin: 0, fontStyle: 'italic', whiteSpace: 'pre-line', display: '-webkit-box', WebkitLineClamp: 4, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}
          title={letter.note_text}
        >
          &ldquo;{letter.note_text}&rdquo;
        </p>
      )}
      {canOpen && (
        <Button size="sm" variant="primary" icon="mail" loading={opening} onClick={doOpen}>
          Open letter
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
  const account = useAccount((s) => s.current);
  const [letters, setLetters] = useState<LetterView[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [fileKey, setFileKey] = useState(0);
  const [recipients, setRecipients] = useState<Set<string> | null>(null); // null = everyone else (the default)
  const [text, setText] = useState('');
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState('');
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    try {
      setLetters(await listLetters(projectId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not load letters.');
    }
  }, [projectId]);

  // Refetch on account switch too: what a letter shows depends on who is looking.
  useEffect(() => {
    setLetters([]);
    setRecipients(null);
    setError('');
    setSent('');
    void refresh();
    const timer = setInterval(() => {
      if (!document.hidden) void refresh();
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [refresh, account]);

  const otherContributors = contributors.filter((c) => c.contributor_id !== myContributorId);
  const chosen = recipients ?? new Set(otherContributors.map((c) => c.contributor_id));
  const toggleRecipient = (id: string) => {
    const next = new Set(chosen);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setRecipients(next);
  };

  const send = async () => {
    if (!myContributorId || chosen.size === 0 || (!file && !text.trim())) return;
    setSending(true);
    setError('');
    setSent('');
    try {
      const to = otherContributors.filter((c) => chosen.has(c.contributor_id)).map((c) => c.display_name).join(' & ');
      const from = contributors.find((c) => c.contributor_id === myContributorId)?.display_name ?? 'me';
      const page = file ?? (await renderLetterPage(text, from, to || 'you'));
      await createLetter(projectId, page, myContributorId, [...chosen], text.slice(0, LETTER_MAX));
      setFile(null);
      setFileKey((k) => k + 1);
      setText('');
      setRecipients(null);
      setSent(`Sealed and sent to ${to}. Only they can open it.`);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : 'Could not send that letter.');
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="app-section">
      <h2 className="title" style={{ margin: 0 }}>
        Letters ({letters.length})
      </h2>

      {myContributorId ? (
        otherContributors.length === 0 ? (
          <p className="rt-field-hint">Once someone else joins this room, you can write them a sealed letter here.</p>
        ) : (
          <div className="app-panel rt-glass-strong" style={{ margin: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
            <p className="rt-field-hint" style={{ margin: 0 }}>
              Write a letter for someone in this room. It stays sealed until they open it, here or in VR.
            </p>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center' }}>
              <span className="rt-field-hint">To:</span>
              {otherContributors.map((c) => (
                <label key={c.contributor_id} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <input type="checkbox" checked={chosen.has(c.contributor_id)} onChange={() => toggleRecipient(c.contributor_id)} />
                  {c.display_name}
                </label>
              ))}
            </div>
            <Field
              label="Your letter"
              multiline
              rows={5}
              placeholder="Remember the summer we..."
              value={text}
              onChange={(e) => setText(e.target.value)}
              maxLength={LETTER_MAX}
              hint={file ? 'Sent as a note with your attached page.' : "We'll set it on a sheet of paper for you."}
            />
            <label className="rt-field-hint" style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
              Or attach a Notability page (PNG, JPEG or WebP):
              <input key={fileKey} type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            </label>
            <div className="app-actions" style={{ marginTop: 0 }}>
              <Button variant="primary" icon="mail" loading={sending} disabled={(!file && !text.trim()) || chosen.size === 0} onClick={send}>
                Seal and send
              </Button>
              {sent && <span className="rt-field-hint">{sent}</span>}
            </div>
          </div>
        )
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
