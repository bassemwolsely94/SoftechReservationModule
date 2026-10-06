/**
 * MapPicker.jsx — tap-to-drop-pin location picker (Leaflet + free OSM tiles).
 * Props: lat, lng (initial), onPick(lat,lng), height.
 */
import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

// Leaflet's default marker images don't resolve under bundlers — use a CDN icon.
const ICON = L.icon({
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png',
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
  iconSize: [25, 41], iconAnchor: [12, 41],
})

const DEFAULT = [30.0444, 31.2357]  // Cairo fallback

export default function MapPicker({ lat, lng, onPick, height = 240 }) {
  const ref = useRef(null)
  const mapRef = useRef(null)
  const markerRef = useRef(null)

  useEffect(() => {
    if (mapRef.current || !ref.current) return
    const start = (lat != null && lng != null) ? [Number(lat), Number(lng)] : DEFAULT
    const map = L.map(ref.current).setView(start, lat != null ? 15 : 11)
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© OpenStreetMap', maxZoom: 19,
    }).addTo(map)
    const marker = L.marker(start, { draggable: true, icon: ICON }).addTo(map)
    marker.on('dragend', () => { const p = marker.getLatLng(); onPick(+p.lat.toFixed(6), +p.lng.toFixed(6)) })
    map.on('click', (e) => { marker.setLatLng(e.latlng); onPick(+e.latlng.lat.toFixed(6), +e.latlng.lng.toFixed(6)) })
    mapRef.current = map; markerRef.current = marker
    // Leaflet needs a size recalc when shown inside a freshly-opened modal.
    setTimeout(() => map.invalidateSize(), 120)
    return () => { map.remove(); mapRef.current = null }
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  return <div ref={ref} style={{ height, width: '100%', borderRadius: 12, overflow: 'hidden' }} />
}
