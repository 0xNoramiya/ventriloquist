import { useEffect, useState } from 'react';
import { useT } from '../../i18n';
import { defaultPhoneHost, lanHosts, patientUrl, savePhoneHost } from '../../lib/host';
import { Button } from '../Button';
import { inputClass } from '../Form';
import { QRCode } from '../QRCode';
import { isBrowserDemo } from '../../demo/bridge';

/** QR code and link that open the patient view on the phone. */
export function ConnectPanel({ sid, compact = false }: { sid: string; compact?: boolean }) {
  const t = useT();
  if (isBrowserDemo) {
    return <p className="text-[15px] text-ink-soft">{t('demo.connect_note')}</p>;
  }
  return <PhoneLink sid={sid} compact={compact} />;
}

function PhoneLink({ sid, compact }: { sid: string; compact: boolean }) {
  const t = useT();
  const [host, setHost] = useState(defaultPhoneHost);
  const [editing, setEditing] = useState(false);
  const [copied, setCopied] = useState(false);
  const url = patientUrl(host, sid);
  const localUrl = `/patient/${sid}`;
  const hosts = lanHosts();

  useEffect(() => {
    if (!copied) return;
    const id = window.setTimeout(() => setCopied(false), 1500);
    return () => window.clearTimeout(id);
  }, [copied]);

  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
      <div className="shrink-0 self-start rounded-[var(--radius-control)] p-1 shadow-[inset_0_0_0_1px_var(--color-line)]">
        <QRCode value={url} size={compact ? 132 : 168} label={t('connect.qr_label')} />
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-3">
        <p className="text-[15px] text-ink-soft">{t('connect.body')}</p>
        <p className="break-all rounded-[var(--radius-control)] bg-wash px-3 py-2 text-[15px] font-semibold">
          {url}
        </p>
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            onClick={() => {
              void navigator.clipboard?.writeText(url).then(() => setCopied(true));
            }}
          >
            {copied ? t('connect.copied') : t('connect.copy')}
          </Button>
          <a
            href={localUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex min-h-10 items-center rounded-[var(--radius-control)] px-3 text-sm font-semibold underline decoration-line-strong underline-offset-4 hover:bg-wash"
          >
            {t('connect.open_here')}
          </a>
          <Button
            size="sm"
            variant="ghost"
            aria-expanded={editing}
            onClick={() => setEditing((v) => !v)}
          >
            {t('connect.change_host')}
          </Button>
        </div>
        {editing ? (
          <form
            className="flex flex-col gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              savePhoneHost(host);
              setEditing(false);
            }}
          >
            <label htmlFor="phone-host" className="text-sm font-semibold">
              {t('connect.host_label')}
            </label>
            <div className="flex gap-2">
              <input
                id="phone-host"
                className={inputClass}
                value={host}
                list="lan-hosts"
                onChange={(e) => setHost(e.target.value.trim())}
                spellCheck={false}
                autoCapitalize="off"
              />
              <Button type="submit" className="shrink-0">
                {t('connect.save_host')}
              </Button>
            </div>
            <datalist id="lan-hosts">
              {hosts.map((h) => (
                <option key={h} value={`${h}:${window.location.port || '5173'}`} />
              ))}
            </datalist>
            <p className="text-sm text-muted">{t('connect.host_hint')}</p>
          </form>
        ) : null}
      </div>
    </div>
  );
}
