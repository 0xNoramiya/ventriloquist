import { describe, expect, it } from 'vitest';
import { snapshot } from '../test/fixtures';
import { dismissBanner, initialSession, reduceServerMessage } from './session';

describe('reduceServerMessage', () => {
  it('stores the snapshot and marks the connection open', () => {
    const s = reduceServerMessage(initialSession, { type: 'snapshot', snapshot: snapshot() });
    expect(s.snapshot?.prompt?.id).toBe('p2');
    expect(s.connection).toBe('open');
    expect(s.alarm.active).toBe(false);
  });

  it('raises the alarm on an alarm event and bumps the sequence', () => {
    const s = reduceServerMessage(initialSession, {
      type: 'snapshot',
      snapshot: snapshot({ state: 'EMERGENCY', emergency: true, prompt: null }),
      event: {
        type: 'alarm',
        text: 'Pasien butuh bantuan sekarang.',
        text_en: 'The patient needs help now.',
      },
    });
    expect(s.alarm).toEqual({
      active: true,
      text: 'Pasien butuh bantuan sekarang.',
      textEn: 'The patient needs help now.',
    });
    expect(s.alarmSeq).toBe(1);
  });

  it('raises the alarm when joining a session that is already in emergency', () => {
    const s = reduceServerMessage(initialSession, {
      type: 'snapshot',
      snapshot: snapshot({ state: 'EMERGENCY', emergency: true }),
    });
    expect(s.alarm.active).toBe(true);
  });

  it('clears the alarm once the snapshot says the emergency was acknowledged', () => {
    const raised = reduceServerMessage(initialSession, {
      type: 'snapshot',
      snapshot: snapshot({ emergency: true }),
      event: { type: 'alarm', text: 'x' },
    });
    const acked = reduceServerMessage(raised, {
      type: 'snapshot',
      snapshot: snapshot({ state: 'PAUSED', emergency: false }),
    });
    expect(acked.alarm.active).toBe(false);
    expect(acked.alarmSeq).toBe(1);
  });

  it('keeps alert and error events as dismissible banners, newest last, capped', () => {
    let s = initialSession;
    for (let i = 0; i < 6; i += 1) {
      s = reduceServerMessage(s, {
        type: 'snapshot',
        snapshot: snapshot(),
        event: { type: i % 2 ? 'error' : 'alert', text: `event ${i}` },
      });
    }
    expect(s.banners.map((b) => b.text)).toEqual(['event 2', 'event 3', 'event 4', 'event 5']);
    const after = dismissBanner(s, s.banners[0]!.id);
    expect(after.banners).toHaveLength(3);
  });

  it('ignores sensitive events for banners (the caregiver_reason drives that banner)', () => {
    const s = reduceServerMessage(initialSession, {
      type: 'snapshot',
      snapshot: snapshot({ caregiver_reason: 'sensitive_verify' }),
      event: { type: 'sensitive', message_id: 'msg_1' },
    });
    expect(s.banners).toHaveLength(0);
  });

  it('marks the session missing on a server error and ignores pongs', () => {
    expect(reduceServerMessage(initialSession, { type: 'pong' })).toBe(initialSession);
    expect(
      reduceServerMessage(initialSession, { type: 'error', error: 'session not found' }).connection,
    ).toBe('missing');
  });
});
