/**
 * ErrorBoundary — never a blank screen again (owner 2026-10-05). If anything inside throws
 * while rendering, a short calm message with «إعادة تحميل الصفحة» replaces it.
 *
 *   <ErrorBoundary scope="page" resetKey={location.pathname}>  — around each page (Layout):
 *       the sidebar keeps working; moving to another page clears the error by itself.
 *   <ErrorBoundary scope="app">                                — around the whole app (main.jsx):
 *       the last safety net (layout, login, mobile, portal).
 *
 * A stale build after an update ("Failed to fetch dynamically imported module") is told
 * apart: the message says a new version is available and the reload fixes it.
 * The technical detail is folded away (with a copy button) for whoever reports the issue.
 * Inline styles + theme variables only, so the screen still renders if CSS / the app is broken.
 */
import { Component } from 'react'

const STALE_RE = /dynamically imported module|Importing a module script failed|ChunkLoadError|Loading chunk/i

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null, info: null, copied: false }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    this.setState({ info })
    // eslint-disable-next-line no-console
    console.error('[ErrorBoundary]', this.props.scope || 'page', error, info?.componentStack)
  }

  componentDidUpdate(prev) {
    // a different page was opened → try rendering again
    if (this.state.error && prev.resetKey !== this.props.resetKey) {
      this.setState({ error: null, info: null, copied: false })
    }
  }

  details() {
    const { error, info } = this.state
    return [
      `${new Date().toISOString()} · ${window.location.href}`,
      String(error?.stack || error?.message || error),
      (info?.componentStack || '').trim().split('\n').slice(0, 8).join('\n'),
    ].join('\n\n')
  }

  copy = async () => {
    try {
      await navigator.clipboard.writeText(this.details())
      this.setState({ copied: true })
    } catch { /* clipboard blocked — the details are visible to select by hand */ }
  }

  render() {
    const { error, copied } = this.state
    if (!error) return this.props.children
    const stale = STALE_RE.test(String(error?.message || error))
    const app = this.props.scope === 'app'
    const box = {
      maxWidth: 520, margin: app ? '12vh auto' : '8vh auto', padding: '24px 28px', borderRadius: 12,
      background: 'rgb(var(--c-surface, 255 255 255))', color: 'rgb(var(--c-content, 17 24 39))',
      border: '1px solid rgb(var(--c-line, 229 231 235))', boxShadow: '0 4px 18px rgba(0,0,0,.06)',
      fontFamily: 'inherit', textAlign: 'center', direction: 'rtl',
    }
    const btn = (primary) => ({
      padding: '8px 18px', borderRadius: 8, fontSize: 14, cursor: 'pointer', fontFamily: 'inherit',
      border: primary ? 'none' : '1px solid rgb(var(--c-line, 229 231 235))',
      background: primary ? 'rgb(var(--c-brand-600, 2 40 113))' : 'transparent',
      color: primary ? '#fff' : 'inherit',
    })
    return (
      <div role="alert" style={{ padding: 16, minHeight: app ? '100vh' : undefined,
        background: app ? 'rgb(var(--c-bg, 246 247 249))' : undefined }}>
        <div style={box}>
          <div style={{ fontSize: 34, lineHeight: 1 }}>{stale ? '🔄' : '⚠️'}</div>
          <h2 style={{ fontSize: 18, fontWeight: 700, margin: '12px 0 6px' }}>
            {stale ? 'يوجد إصدار أحدث من النظام' : 'حدث خطأ أثناء عرض هذه الصفحة'}
          </h2>
          <p style={{ fontSize: 14, opacity: 0.75, margin: '0 0 18px', lineHeight: 1.7 }}>
            {stale
              ? 'تم تحديث النظام أثناء فتح الصفحة. أعد التحميل لاستخدام الإصدار الجديد.'
              : 'لم تُحفظ أي تغييرات ناقصة بسبب هذا الخطأ. أعد تحميل الصفحة، وإذا تكرر الخطأ أبلغ الدعم الفني.'}
          </p>
          <div style={{ display: 'flex', gap: 8, justifyContent: 'center', flexWrap: 'wrap' }}>
            <button type="button" style={btn(true)} onClick={() => window.location.reload()}>
              إعادة تحميل الصفحة
            </button>
            {!stale && (
              <button type="button" style={btn(false)} onClick={() => { window.location.href = '/' }}>
                الصفحة الرئيسية
              </button>
            )}
          </div>
          {!stale && (
            <details style={{ marginTop: 18, textAlign: 'start', fontSize: 12, opacity: 0.7 }}>
              <summary style={{ cursor: 'pointer' }}>تفاصيل تقنية (للدعم الفني)</summary>
              <pre dir="ltr" style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 180,
                overflow: 'auto', margin: '8px 0', fontSize: 11 }}>{this.details()}</pre>
              <button type="button" style={{ ...btn(false), padding: '4px 10px', fontSize: 12 }} onClick={this.copy}>
                {copied ? 'تم النسخ ✓' : 'نسخ التفاصيل'}
              </button>
            </details>
          )}
        </div>
      </div>
    )
  }
}
