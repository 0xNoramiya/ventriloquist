import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import type { FamilyMember, Honorific, Lang, Patient } from '../api/types';
import { Button, LinkButton } from '../components/Button';
import { Field, Notice, Select, TextInput, inputClass } from '../components/Form';
import { Shell } from '../components/Shell';
import { useT } from '../i18n';
import { cx } from '../lib/format';

const RELATIONS = [
  'daughter',
  'son',
  'wife',
  'husband',
  'mother',
  'father',
  'sister',
  'brother',
  'grandchild',
  'friend',
];

export default function Setup() {
  const t = useT();
  const navigate = useNavigate();
  const [name, setName] = useState('');
  const [language, setLanguage] = useState<Lang>('en');
  const [honorific, setHonorific] = useState<Honorific>('Anda');
  const [family, setFamily] = useState<FamilyMember[]>([{ name: '', relation: '' }]);
  const [notes, setNotes] = useState('');
  const [spiritual, setSpiritual] = useState('');
  const [consent, setConsent] = useState(false);
  const [errors, setErrors] = useState<{ name?: string; consent?: string; form?: string }>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<Patient | null>(null);
  const [starting, setStarting] = useState(false);

  function updateMember(i: number, patch: Partial<FamilyMember>) {
    setFamily((f) => f.map((m, j) => (j === i ? { ...m, ...patch } : m)));
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const next: typeof errors = {};
    if (!name.trim()) next.name = t('setup.error.name');
    if (!consent) next.consent = t('setup.error.consent');
    setErrors(next);
    if (next.name || next.consent) return;
    setSaving(true);
    try {
      const patient = await api.createPatient({
        display_name: name.trim(),
        language,
        honorific,
        family: family
          .map((m) => ({ name: m.name.trim(), relation: m.relation.trim() }))
          .filter((m) => m.name && m.relation),
        notes: notes
          .split('\n')
          .map((n) => n.trim())
          .filter(Boolean)
          .slice(0, 20),
        spiritual_preference: spiritual.trim() || null,
        simulation_consent: consent,
      });
      setSaved(patient);
    } catch (err) {
      setErrors({ form: err instanceof Error ? err.message : String(err) });
    } finally {
      setSaving(false);
    }
  }

  async function skipAndStart() {
    if (!saved) return;
    setStarting(true);
    try {
      await api.finalizeCalibration(saved.id, { skip: true });
      const snap = await api.createSession({ patient_id: saved.id });
      navigate(`/caregiver/${snap.session_id}`);
    } catch (err) {
      setErrors({ form: err instanceof Error ? err.message : String(err) });
      setStarting(false);
    }
  }

  if (saved) {
    return (
      <Shell>
        <div className="mx-auto flex max-w-[640px] flex-col gap-6">
          <h1 className="text-[36px] font-bold">
            {t('setup.saved.title', { name: saved.display_name })}
          </h1>
          <p className="text-lg text-ink-soft">{t('setup.saved.body')}</p>
          {errors.form ? <Notice tone="error">{errors.form}</Notice> : null}
          <div className="flex flex-col gap-3 sm:flex-row">
            <LinkButton to={`/calibrate/${saved.id}`} variant="primary" size="lg">
              {t('setup.saved.calibrate')}
            </LinkButton>
            <Button size="lg" busy={starting} onClick={() => void skipAndStart()}>
              {t('setup.saved.skip')}
            </Button>
          </div>
          <p className="text-[15px] text-muted">{t('setup.saved.skip_hint')}</p>
        </div>
      </Shell>
    );
  }

  return (
    <Shell>
      <div className="mx-auto max-w-[720px]">
        <h1 className="text-[36px] font-bold">{t('setup.title')}</h1>
        <p className="mt-2 max-w-[60ch] text-lg text-ink-soft">{t('setup.lead')}</p>

        <form noValidate onSubmit={(e) => void submit(e)} className="mt-8 flex flex-col gap-8">
          <fieldset className="flex flex-col gap-5">
            <legend className="mb-4 text-xl font-bold">{t('setup.section.person')}</legend>
            <Field label={t('setup.name')} hint={t('setup.name_hint')} error={errors.name}>
              {(p) => (
                <TextInput
                  {...p}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  autoComplete="off"
                  maxLength={80}
                  required
                />
              )}
            </Field>
            <div className="grid gap-5 sm:grid-cols-2">
              <Field label={t('setup.language')}>
                {(p) => (
                  <Select
                    {...p}
                    value={language}
                    onChange={(e) => setLanguage(e.target.value as Lang)}
                  >
                    <option value="en">English</option>
                    <option value="id">Bahasa Indonesia</option>
                  </Select>
                )}
              </Field>
              <Field label={t('setup.honorific')} hint={t('setup.honorific_hint')}>
                {(p) => (
                  <Select
                    {...p}
                    value={honorific}
                    onChange={(e) => setHonorific(e.target.value as Honorific)}
                  >
                    <option value="Bapak">Bapak</option>
                    <option value="Ibu">Ibu</option>
                    <option value="Anda">Anda</option>
                  </Select>
                )}
              </Field>
            </div>
          </fieldset>

          <fieldset className="flex flex-col gap-3">
            <legend className="mb-1 text-xl font-bold">{t('setup.section.family')}</legend>
            <p className="text-[15px] text-muted">{t('setup.family_hint')}</p>
            <datalist id="relations">
              {RELATIONS.map((r) => (
                <option key={r} value={r} />
              ))}
            </datalist>
            <ul className="flex flex-col gap-3">
              {family.map((m, i) => (
                <li key={i} className="grid grid-cols-[1fr_1fr_auto] items-end gap-2 sm:gap-3">
                  <label className="flex flex-col gap-1.5">
                    <span className={cx('text-sm font-semibold', i > 0 && 'sr-only')}>
                      {t('setup.family_name')}
                    </span>
                    <input
                      className={inputClass}
                      value={m.name}
                      maxLength={60}
                      onChange={(e) => updateMember(i, { name: e.target.value })}
                      aria-label={i > 0 ? `${t('setup.family_name')} ${i + 1}` : undefined}
                    />
                  </label>
                  <label className="flex flex-col gap-1.5">
                    <span className={cx('text-sm font-semibold', i > 0 && 'sr-only')}>
                      {t('setup.family_relation')}
                    </span>
                    <input
                      className={inputClass}
                      list="relations"
                      value={m.relation}
                      maxLength={40}
                      onChange={(e) => updateMember(i, { relation: e.target.value })}
                      aria-label={i > 0 ? `${t('setup.family_relation')} ${i + 1}` : undefined}
                    />
                  </label>
                  <Button
                    variant="ghost"
                    aria-label={t('setup.family_remove', { n: i + 1 })}
                    onClick={() =>
                      setFamily((f) =>
                        f.length > 1 ? f.filter((_, j) => j !== i) : [{ name: '', relation: '' }],
                      )
                    }
                  >
                    <svg viewBox="0 0 20 20" className="size-5" aria-hidden="true">
                      <path
                        d="M5 5l10 10M15 5L5 15"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                      />
                    </svg>
                  </Button>
                </li>
              ))}
            </ul>
            <div>
              <Button
                variant="ghost"
                disabled={family.length >= 12}
                onClick={() => setFamily((f) => [...f, { name: '', relation: '' }])}
                className="-ml-2"
              >
                {t('setup.family_add')}
              </Button>
            </div>
          </fieldset>

          <fieldset className="flex flex-col gap-5">
            <legend className="mb-4 text-xl font-bold">{t('setup.section.notes')}</legend>
            <Field label={t('setup.notes')} hint={t('setup.notes_hint')}>
              {(p) => (
                <textarea
                  {...p}
                  className={cx(inputClass, 'min-h-28 py-2.5')}
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  rows={3}
                />
              )}
            </Field>
            <Field label={t('setup.spiritual')} hint={t('setup.spiritual_hint')}>
              {(p) => (
                <TextInput
                  {...p}
                  value={spiritual}
                  maxLength={60}
                  onChange={(e) => setSpiritual(e.target.value)}
                />
              )}
            </Field>
          </fieldset>

          <div className="flex flex-col gap-2 rounded-[var(--radius-panel)] bg-paper p-4 shadow-[inset_0_0_0_1px_var(--color-line)]">
            <label className="flex cursor-pointer items-start gap-3">
              <input
                type="checkbox"
                checked={consent}
                onChange={(e) => setConsent(e.target.checked)}
                className="mt-0.5 size-6 shrink-0 accent-[var(--color-ink)]"
                aria-describedby="consent-hint"
                aria-invalid={errors.consent ? true : undefined}
                required
              />
              <span className="font-semibold">{t('setup.consent')}</span>
            </label>
            <p id="consent-hint" className="pl-9 text-sm text-muted">
              {t('setup.consent_hint')}
            </p>
            {errors.consent ? (
              <p className="pl-9 text-sm font-semibold text-alarm" role="alert">
                {errors.consent}
              </p>
            ) : null}
          </div>

          {errors.form ? <Notice tone="error">{errors.form}</Notice> : null}
          <div>
            <Button type="submit" variant="primary" size="lg" busy={saving}>
              {t('setup.save')}
            </Button>
          </div>
        </form>
      </div>
    </Shell>
  );
}
