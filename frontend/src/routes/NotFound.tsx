import { LinkButton } from '../components/Button';
import { Shell } from '../components/Shell';
import { useT } from '../i18n';

export default function NotFound() {
  const t = useT();
  return (
    <Shell>
      <div className="mx-auto flex max-w-[640px] flex-col gap-4">
        <h1 className="text-[34px] font-bold">{t('notfound.title')}</h1>
        <p className="text-lg text-ink-soft">{t('notfound.body')}</p>
        <div>
          <LinkButton to="/" variant="primary">
            {t('notfound.home')}
          </LinkButton>
        </div>
      </div>
    </Shell>
  );
}
