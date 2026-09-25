import { useEffect, useState } from 'react';
import type { DesktopSkill } from '../../../shared/wire';
import { Icon } from './Icons';

function errorText(error: unknown) {
  return (error instanceof Error ? error.message : String(error)).replace(/^Error invoking remote method ['"]engine:invoke['"]:\s*(?:Error:\s*)?/, '');
}

export function SkillsSection() {
  const [skills, setSkills] = useState<DesktopSkill[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');

  useEffect(() => {
    let active = true;
    void window.ankita.invoke<DesktopSkill[]>('listSkills')
      .then(list => { if (active) setSkills(list); })
      .catch(cause => { if (active) setError(errorText(cause)); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!selected) return;
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') setSelected(null); };
    window.addEventListener('keydown', close);
    return () => window.removeEventListener('keydown', close);
  }, [selected]);

  const toggle = async (skill: DesktopSkill) => {
    if (busy) return;
    setBusy(skill.name); setError('');
    try {
      const list = await window.ankita.invoke<DesktopSkill[]>('setSkillEnabled', { name: skill.name, enabled: !skill.enabled });
      setSkills(list);
    } catch (cause) { setError(errorText(cause)); }
    finally { setBusy(null); }
  };

  const visible = (skills || []).filter(skill => `${skill.name} ${skill.description}`.toLowerCase().includes(query.toLowerCase()));
  const detail = skills?.find(skill => skill.name === selected);
  const enabledCount = skills?.filter(skill => skill.enabled).length || 0;

  return <>
    <div className="plugins-intro skills-intro"><div className="plugins-eyebrow"><span /> INSTALLED WORKFLOWS</div><h1>Make room for<br /><em>better habits.</em></h1><p>Skills give Ankita focused instructions for specific work. Choose which ones are available in your chats.</p></div>
    {error && <div className="plugins-alert" role="alert"><Icon name="alert" size={16} /><span>{error}</span><button type="button" onClick={() => setError('')} aria-label="Dismiss error"><Icon name="close" size={15} /></button></div>}
    <div className="plugins-toolbar"><div className="plugins-tabs"><span className="skills-tab-label">Installed skills <small>{skills?.length || 0}</small></span></div><span className="plugins-connection live"><i />{enabledCount} enabled</span></div>
    {skills === null && !error ? <div className="plugins-loading">Loading skills…</div> : skills?.length === 0 ? <div className="plugins-empty"><Icon name="file" size={22} /><h2>No skills installed</h2><p>Installed skills will appear here.</p></div> : <>
      <label className="plugins-search"><Icon name="search" size={18} /><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search installed skills" aria-label="Search installed skills" /></label>
      <section className="plugins-section"><div className="plugins-section-head"><h2>Your skills</h2><span>{enabledCount} of {skills?.length || 0} enabled</span></div>
        {visible.length ? <div className="plugin-grid">{visible.map(skill => <div className="plugin-row skill-row" key={skill.name}>
          <button type="button" className="plugin-row-main" onClick={() => setSelected(skill.name)} aria-label={`View ${skill.name} skill`}><span className="plugin-logo skill-logo"><Icon name="file" size={20} /></span><span className="plugin-row-copy"><strong>{skill.name}</strong><small>{skill.description}</small></span></button>
          <button type="button" className={`skill-toggle ${skill.enabled ? 'on' : ''}`} role="switch" aria-checked={skill.enabled} aria-label={`${skill.enabled ? 'Disable' : 'Enable'} ${skill.name}`} onClick={() => void toggle(skill)} disabled={busy !== null}><span /></button>
        </div>)}</div> : <div className="plugins-empty"><Icon name="search" size={22} /><h2>No skills found</h2><p>Try another name or keyword.</p></div>}
      </section>
    </>}
    {detail && <div className="plugins-drawer-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) setSelected(null); }}><section className="plugins-drawer" role="dialog" aria-modal="true" aria-labelledby="skill-detail-title">
      <div className="plugins-drawer-top"><span>SKILL DETAILS</span><button type="button" className="icon-button" onClick={() => setSelected(null)} aria-label="Close skill details"><Icon name="close" size={17} /></button></div>
      <div className="plugins-drawer-body"><span className="plugin-logo skill-logo"><Icon name="file" size={25} /></span><h2 id="skill-detail-title">{detail.name}</h2><p>{detail.description}</p><div className={`plugins-detail-status ${detail.enabled ? 'connected' : ''}`}><i />{detail.enabled ? 'Enabled for chats' : 'Disabled for chats'}</div>
        <button type="button" className="settings-primary skill-detail-action" onClick={() => void toggle(detail)} disabled={busy !== null}>{busy === detail.name ? 'Saving…' : detail.enabled ? 'Disable skill' : 'Enable skill'}</button>
        {detail.suggestedTools && <div className="skill-detail-tools"><h3>Suggested tools</h3><p>{detail.suggestedTools}</p></div>}
        <div className="skill-detail-instructions"><h3>Instructions</h3><pre>{detail.body}</pre></div>
      </div>
    </section></div>}
  </>;
}
