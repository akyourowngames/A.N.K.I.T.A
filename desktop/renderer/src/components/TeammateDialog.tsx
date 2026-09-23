import { useEffect, useState } from 'react';
import type { Project, Teammate } from '../../../shared/wire';
import { Icon } from './Icons';

const colors = ['#b9a27c', '#8eb8ad', '#8ca8d5', '#b7a0c8', '#d19d87', '#a7b487'];

export function TeammateDialog({ teammate, projects, onSave, onClose }: { teammate?: Teammate | null; projects: Project[]; onSave: (value: { name: string; persona: string; color: string; emoji: string; projectId: string | null }) => void; onClose: () => void }) {
  const [name, setName] = useState(teammate?.name || '');
  const [persona, setPersona] = useState(teammate?.persona || '');
  const [color, setColor] = useState(teammate?.color || colors[0]);
  const [emoji, setEmoji] = useState(teammate?.emoji || '✦');
  const [projectId, setProjectId] = useState(teammate?.projectId || '');
  useEffect(() => { setName(teammate?.name || ''); setPersona(teammate?.persona || ''); setColor(teammate?.color || colors[0]); setEmoji(teammate?.emoji || '✦'); setProjectId(teammate?.projectId || ''); }, [teammate]);
  useEffect(() => { const key = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); }; window.addEventListener('keydown', key); return () => window.removeEventListener('keydown', key); }, [onClose]);
  return <div className="modal-backdrop"><form className="teammate-dialog" role="dialog" aria-modal="true" aria-labelledby="teammate-title" onSubmit={event => { event.preventDefault(); if (name.trim()) onSave({ name: name.trim(), persona: persona.trim(), color, emoji, projectId: projectId || null }); }}>
    <button type="button" className="modal-close icon-button" onClick={onClose} aria-label="Close"><Icon name="close" size={18}/></button>
    <div className="modal-symbol"><Icon name="sparkle" size={23}/></div>
    <h2 id="teammate-title">{teammate ? 'Edit teammate' : 'A new teammate'}</h2>
    <p>Give this space a name and a point of view. Each teammate keeps its own conversation.</p>
    <label>Name<input autoFocus value={name} maxLength={48} onChange={event => setName(event.target.value)} placeholder="e.g. Research desk" required /></label>
    <label>What should they focus on?<textarea value={persona} maxLength={4000} onChange={event => setPersona(event.target.value)} placeholder="Describe their role, style, and what they help you with." rows={4} /></label>
    <label>Project<select value={projectId} onChange={event => setProjectId(event.target.value)}><option value="">No project</option>{projects.filter(project => !project.archived).map(project => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
    <div className="dialog-palette"><span>Appearance</span><div className="palette-controls"><input className="emoji-input" aria-label="Avatar symbol" value={emoji} maxLength={4} onChange={event => setEmoji(event.target.value)} />{colors.map(option => <button type="button" key={option} className={`color-swatch ${color === option ? 'selected' : ''}`} style={{ background: option }} onClick={() => setColor(option)} aria-label={`Choose ${option}`} />)}</div></div>
    <div className="dialog-actions"><button type="button" className="button-quiet" onClick={onClose}>Cancel</button><button type="submit" className="button-primary" disabled={!name.trim()}>{teammate ? 'Save changes' : 'Create teammate'}</button></div>
  </form></div>;
}
