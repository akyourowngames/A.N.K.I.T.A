import { Icon } from './Icons';
import { useEffect, useState } from 'react';
import { DEFAULT_PERSONALITY, PERSONALITY_ACTIONS, PERSONALITY_LIMITS, PERSONALITY_OPTIONS, normalizePersonality, type PersonalityProfile, type PersonalityView } from '../../../../src/core/personality.mjs';
import { cleanErrorMessage } from '../../../shared/error-notices.mjs';
import './personality-settings.css';

export function PersonalitySettings() {
  const [draft, setDraft] = useState<PersonalityProfile | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ error: boolean; text: string } | null>(null);
  useEffect(() => {
    let active = true;
    void window.ankita.invoke<PersonalityView>(PERSONALITY_ACTIONS.get).then(view => {
      if (active) { setDraft(view.profile); if (view.notice) setNotice({ error: true, text: view.notice }); }
    }).catch(error => { if (active) setNotice({ error: true, text: cleanErrorMessage(error) }); });
    return () => { active = false; };
  }, []);
  const set = <K extends keyof PersonalityProfile>(key: K, value: PersonalityProfile[K]) => {
    setDraft(current => current ? { ...current, [key]: value } : current); setNotice(null);
  };
  const save = async () => {
    if (!draft || busy) return;
    setBusy(true); setNotice(null);
    try {
      const view = await window.ankita.invoke<PersonalityView>(PERSONALITY_ACTIONS.save, normalizePersonality(draft));
      setDraft(view.profile); setNotice({ error: false, text: 'Personality saved. New replies will use this style.' });
    } catch (error) { setNotice({ error: true, text: cleanErrorMessage(error) }); }
    finally { setBusy(false); }
  };
  const example = (index: number, key: 'user' | 'assistant', value: string) => {
    if (draft) set('examples', draft.examples.map((item, at) => at === index ? { ...item, [key]: value } : item));
  };
  return <div className="settings-content personality-settings">
    <div className="settings-heading"><span className="settings-heading-icon"><Icon name="sparkle" size={20} /></span><h1 id="settings-title">Personality</h1><p>Give her a voice that feels familiar.</p></div>
    {notice && <p role={notice.error ? 'alert' : 'status'} className="settings-help">{notice.text}</p>}
    {!draft ? <p role="status">Loading personality...</p> : <>
      <section className="settings-panel">
        <label className="personality-enabled"><input type="checkbox" checked={draft.enabled} onChange={event => set('enabled', event.target.checked)} /><span>Use this personality<small>Turn it off for a plain, task-focused style.</small></span></label>
        <div className="settings-field"><label htmlFor="personality-character">Character</label>
          <textarea id="personality-character" rows={3} maxLength={PERSONALITY_LIMITS.description} value={draft.description} onChange={event => set('description', event.target.value)} />
          <small>Describe her in your words. This guides fresh replies; it is not a script.</small></div>
        <div className="settings-form-pair">{(['attitude', 'teasing'] as const).map(key => <div className="settings-field" key={key}><label htmlFor={`personality-${key}`}>{key === 'attitude' ? 'Attitude' : 'Teasing'}</label>
          <select className="settings-select" id={`personality-${key}`} value={draft[key]} onChange={event => set(key, event.target.value as PersonalityProfile[typeof key])}>{Object.entries(PERSONALITY_OPTIONS[key]).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div>)}</div>
        <div className="settings-field"><label htmlFor="personality-language">Speaking language</label><select className="settings-select" id="personality-language" value={draft.language} onChange={event => set('language', event.target.value as PersonalityProfile['language'])}>{Object.entries(PERSONALITY_OPTIONS.language).map(([value,label]) => <option key={value} value={value}>{label}</option>)}</select></div>
        <div className="settings-field"><label htmlFor="personality-care">Care and respect</label><textarea id="personality-care" rows={3} maxLength={PERSONALITY_LIMITS.care} value={draft.care} onChange={event => set('care', event.target.value)} /><small>When should she soften her tone, listen or keep things serious?</small></div>
      </section>
      <details className="personality-examples"><summary>Example exchanges <span>{draft.examples.length}</span></summary>
        <p className="settings-help">A few examples teach rhythm and attitude. She writes her own replies each time.</p>
        {draft.examples.map((item,index) => <div className="personality-example" key={index}>
          <div className="settings-field"><label htmlFor={`personality-message-${index}`}>Example message {index+1}</label><textarea id={`personality-message-${index}`} rows={2} maxLength={PERSONALITY_LIMITS.user} value={item.user} onChange={event => example(index,'user',event.target.value)} /></div>
          <div className="settings-field"><label htmlFor={`personality-reply-${index}`}>Example reply {index+1}</label><textarea id={`personality-reply-${index}`} rows={2} maxLength={PERSONALITY_LIMITS.assistant} value={item.assistant} onChange={event => example(index,'assistant',event.target.value)} /></div>
          <button type="button" className="settings-secondary" aria-label={`Remove example ${index+1}`} onClick={() => set('examples',draft.examples.filter((_,at)=>at!==index))}>Remove example</button>
        </div>)}
        <button type="button" className="settings-secondary" disabled={draft.examples.length >= PERSONALITY_LIMITS.examples} onClick={() => set('examples',[...draft.examples,{user:'',assistant:''}])}>Add example</button>
      </details>
      <p className="settings-help">Voice and connected model chats use this style. A linked ChatGPT conversation keeps its own instructions. Facts, work results and permissions always come first.</p>
      <div className="settings-savebar"><button type="button" className="settings-secondary" disabled={busy} onClick={() => { setDraft(normalizePersonality(DEFAULT_PERSONALITY)); setNotice(null); }}>Restore default</button><button type="button" className="settings-primary" disabled={busy} onClick={save}>{busy ? 'Saving...' : 'Save personality'}</button></div>
    </>}
  </div>;
}
