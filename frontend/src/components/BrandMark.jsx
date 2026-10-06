/**
 * BrandMark — official ElRezeiky hexagon logo mark.
 *
 * Renders the real eel-R hexagon (extracted from the brand-book source at
 * public/brand/logo-mark.png). The mark has a white hexagon interior, so it
 * reads cleanly on both light and dark backgrounds.
 *
 * Props:
 *   size      – px (default 40)
 *   className – extra classes
 *   title     – accessible label
 */
export default function BrandMark({ size = 40, className = '', title = 'صيدليات الرزيقي' }) {
  return (
    <img
      src="/brand/logo-mark.png"
      width={size}
      height={size}
      alt={title}
      className={className}
      style={{ objectFit: 'contain', display: 'block' }}
      draggable={false}
    />
  )
}
