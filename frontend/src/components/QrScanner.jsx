/**
 * QrScanner.jsx — camera QR scanner for the customer code (/m/customers).
 * A thin wrapper over BarcodeScanner (native BarcodeDetector, bundled decoder on iPhone).
 *
 * Props: onScan(text) — called once with the decoded value; onClose().
 */
import BarcodeScanner from './BarcodeScanner'

export default function QrScanner({ onScan, onClose }) {
  return (
    <BarcodeScanner onScan={onScan} onClose={onClose} formats={['qr_code']}
      hint="وجّه الكاميرا نحو رمز العميل" />
  )
}
