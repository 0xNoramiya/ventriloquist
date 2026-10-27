import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Button, LinkButton } from '../components/Button';
import { Notice } from '../components/Form';
import { Badge, Section } from '../components/Section';
import { Shell } from '../components/Shell';
import {
  AlarmBanner,
  BudgetMeter,
  CaregiverBanners,
  ModeBadge,
  SoundButton,
} from '../components/caregiver/Banners';
import { ConnectPanel } from '../components/caregiver/ConnectPanel';
import { CaregiverEvents, RoomContext, Transcript } from '../components/caregiver/ContextPanels';
import { Messages } from '../components/caregiver/Messages';
import { ModelCalls } from '../components/caregiver/ModelCalls';
import { NowPanel } from '../components/caregiver/NowPanel';
import { OverlayCanvas } from '../components/caregiver/OverlayCanvas';
import { PosteriorBars } from '../components/caregiver/PosteriorBars';
import { Trail } from '../components/caregiver/Trail';
import { useCurrentLang, useT } from '../i18n';
import { pct } from '../lib/format';
import { useConfig } from '../lib/useConfig';
import { useSessionSocket } from '../lib/useSessionSocket';
import { useSession } from '../store/session';

const panel =
  'rounded-[var(--radius-panel)] bg-paper px-4 py-1 shadow-[inset_0_0_0_1px_var(--color-line)] sm:px-5';

export default function Caregiver() {
  const { sid } = useParams<{ sid: string }>();
  useSessionSocket(sid);
  const t = useT();
  const lang = useCurrentLang();
  const snap = useSession((s) => s.snapshot);
  const connection = useSession((s) => s.connection);
  const { config } = useConfig();
  const [showConnect, setShowConnect] = useState(false);

  if (connection === 'missing') {
    return (
      <Shell>
        <div className="mx-auto flex max-w-[640px] flex-col gap-4">
          <h1 className="text-[32px] font-bold">{t('caregiver.missing.title')}</h1>
          <p className="text-lg text-ink-soft">{t('caregiver.missing.body')}</p>
          <div>
            <LinkButton to="/" variant="primary">
              {t('caregiver.missing.home')}
            </LinkButton>
          </div>
        </div>
      </Shell>
    );
  }

  if (!snap || !sid) {
    return (
      <Shell wide>
        <p role="status" className="text-lg text-muted">
          {t('caregiver.loading')}
        </p>
      </Shell>
    );
  }

  const tau = config?.engine.tau_confirm ?? 0.7;
  const notStarted = snap.message_index === 0;
  const connectOpen = notStarted || showConnect;

  return (
    <Shell
      wide
      headerExtra={
        <div className="hidden items-center gap-3 md:flex">
          <SoundButton />
        </div>
      }
    >
      <div className="-mx-4 -mt-8 mb-6 sm:-mx-8">
        <AlarmBanner snap={snap} />
      </div>

      <div className="flex flex-col gap-6">
        <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
          <div className="min-w-0">
            <p className="text-sm text-muted">{t('caregiver.kicker')}</p>
            <h1 className="text-[30px] font-bold leading-tight sm:text-[34px]">
              {snap.patient.display_name}
            </h1>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-muted">
              <ModeBadge mode={snap.mode} />
              <span>
                {t(snap.patient.language === 'id' ? 'caregiver.speaks_id' : 'caregiver.speaks_en')}
              </span>
              <span aria-hidden="true" className="hidden sm:inline">
                ·
              </span>
              <span className="tabular">
                {t('caregiver.error_rates', {
                  a: pct(snap.calibration.error_rates.a),
                  b: pct(snap.calibration.error_rates.b),
                })}
              </span>
              {snap.calibration.skipped ? (
                <Badge tone="outline">{t('caregiver.not_calibrated')}</Badge>
              ) : null}
              {connection === 'reconnecting' ? (
                <Badge tone="caution">{t('caregiver.reconnecting')}</Badge>
              ) : null}
              {snap.ended ? <Badge tone="ink">{t('caregiver.ended')}</Badge> : null}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <BudgetMeter budget={snap.budget} />
            <div className="md:hidden">
              <SoundButton />
            </div>
            {!notStarted ? (
              <Button aria-expanded={showConnect} onClick={() => setShowConnect((v) => !v)}>
                {t('caregiver.patient_screen')}
              </Button>
            ) : null}
            <LinkButton to={`/memory/${snap.patient.id}`}>{t('caregiver.memory')}</LinkButton>
          </div>
        </div>

        <CaregiverBanners snap={snap} />

        {connectOpen ? (
          <Section id="connect-title" title={t('connect.title')} className={`${panel} py-4`}>
            <ConnectPanel sid={sid} compact={!notStarted} />
          </Section>
        ) : null}

        <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-x-8 gap-y-8 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
          <div className="flex min-w-0 flex-col gap-8">
            <NowPanel snap={snap} />
            <Section
              id="bars-title"
              title={t('bars.title')}
              meta={t('bars.meta', { tau: pct(tau) })}
            >
              <div className={panel}>
                <PosteriorBars
                  posterior={snap.posterior}
                  otherP={snap.other_p}
                  evidence={snap.evidence}
                  tau={tau}
                  lang={lang}
                />
              </div>
            </Section>
            <Section id="context-title" title={t('context.title')} meta={t('context.meta')}>
              <RoomContext evidence={snap.evidence} />
            </Section>
            <Section id="events-title" title={t('event.title')}>
              <CaregiverEvents sid={sid} />
            </Section>
          </div>

          <div className="flex min-w-0 flex-col gap-8">
            <Section id="messages-title" title={t('messages.title')}>
              <Messages messages={snap.messages} current={snap.message} lang={lang} />
            </Section>
            <Section
              id="trail-title"
              title={t('trail.title')}
              meta={snap.message_index > 0 ? t('trail.meta', { n: snap.message_index }) : undefined}
            >
              <div className={panel}>
                <Trail trail={snap.trail} patientLang={snap.patient.language} />
              </div>
            </Section>
            <Section id="transcript-title" title={t('transcript.title')}>
              <Transcript
                sid={sid}
                evidence={snap.evidence}
                mock={snap.mode.effective === 'mock'}
              />
            </Section>
            <Section id="overlay-title" title={t('overlay.title')}>
              <OverlayCanvas overlay={snap.overlay} mock={snap.mode.effective === 'mock'} />
            </Section>
            <Section id="calls-title" title={t('calls.title')}>
              <ModelCalls calls={snap.llm_calls} />
            </Section>
            {config ? null : (
              <Notice tone="caution">
                {t('error.backend')}{' '}
                <Link to="/settings" className="underline">
                  {t('nav.settings')}
                </Link>
              </Notice>
            )}
          </div>
        </div>
      </div>
    </Shell>
  );
}
