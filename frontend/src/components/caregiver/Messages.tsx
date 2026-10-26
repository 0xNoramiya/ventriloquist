import type { Lang, PatientMessage } from '../../api/types';
import { useT } from '../../i18n';
import { clockTime, cx } from '../../lib/format';
import { Pictogram } from '../Pictogram';
import { Badge } from '../Section';

export function Messages({
  messages,
  current,
  lang,
}: {
  messages: PatientMessage[];
  current: PatientMessage | null;
  lang: Lang;
}) {
  const t = useT();
  const list = [...messages];
  if (current && !list.some((m) => m.id === current.id)) list.push(current);
  if (!list.length) return <p className="text-muted">{t('messages.empty')}</p>;

  return (
    <ol className="flex flex-col gap-3">
      {[...list].reverse().map((m) => {
        const text = lang === 'id' ? m.text_id : m.text_en;
        const retracted = m.status === 'retracted';
        return (
          <li
            key={m.id}
            className={cx(
              'flex gap-3 rounded-[var(--radius-control)] px-4 py-3',
              retracted
                ? 'bg-wash'
                : m.status === 'confirmed'
                  ? 'bg-voice-soft'
                  : 'bg-paper shadow-[inset_0_0_0_1px_var(--color-line-strong)]',
            )}
          >
            <Pictogram id={m.hypothesis_id} size={44} className="mt-0.5 rounded-[8px]" />
            <div className="min-w-0 flex-1">
              <p
                className={cx(
                  'text-sm font-semibold',
                  retracted ? 'text-muted' : 'text-voice-deep',
                )}
              >
                {retracted
                  ? t('message.retracted_label')
                  : m.status === 'confirmed'
                    ? t('message.confirmed_label')
                    : m.status === 'needs_verification'
                      ? t('message.verify_label')
                      : t('message.speaking_label')}
              </p>
              <p
                className={cx(
                  'mt-0.5 text-xl font-bold leading-snug',
                  retracted && 'text-muted line-through decoration-2',
                )}
              >
                “{text}”
              </p>
              <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-sm text-muted">
                <span className="tabular">{t('messages.questions', { n: m.questions })}</span>
                <span>{t(`messages.source.${m.source}` as 'messages.source.engine')}</span>
                {m.at ? <span className="tabular">{clockTime(m.at)}</span> : null}
                {m.urgent ? <Badge tone="alarm">{t('bars.urgent')}</Badge> : null}
                {m.sensitive ? <Badge tone="caution">{t('messages.sensitive')}</Badge> : null}
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
