// S4 — local grid filters follow the system search rules (* and % wildcards).
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import MultiSelectFilter from '../components/MultiSelectFilter'
import BranchSelect from '../components/BranchSelect'
import NotificationPanel from '../components/NotificationPanel'
afterEach(cleanup)

describe('MultiSelectFilter', () => {
  const options = [
    { code: '10023', name: 'PANADOL EXTRA' },
    { code: '20045', name: 'VOLTAREN 50' },
  ]
  const open = () => {
    render(<MultiSelectFilter options={options} selected={[]} onChange={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: /الكل/ }))
    return screen.getByPlaceholderText('بحث...')
  }

  it('matches a wildcard across the name', () => {
    const box = open()
    fireEvent.change(box, { target: { value: 'pan*xtra' } })
    expect(screen.getByText('PANADOL EXTRA')).toBeTruthy()
    expect(screen.queryByText('VOLTAREN 50')).toBeNull()
  })

  it('still matches by code', () => {
    const box = open()
    fireEvent.change(box, { target: { value: '10023' } })
    expect(screen.getByText('PANADOL EXTRA')).toBeTruthy()
    expect(screen.queryByText('VOLTAREN 50')).toBeNull()
  })

  it('matches a wildcard across the code', () => {
    const box = open()
    fireEvent.change(box, { target: { value: '100*23' } })
    expect(screen.getByText('PANADOL EXTRA')).toBeTruthy()
  })
})

describe('BranchSelect', () => {
  const branches = [
    { id: 1, softech_branch_id: 'B07', code: 'MAD', name: 'Maadi', name_ar: '' },
    { id: 2, softech_branch_id: 'B09', code: 'NSR', name: 'Nasr City', name_ar: '' },
  ]
  const open = () => {
    render(<BranchSelect branches={branches} value="" onChange={() => {}} />)
    fireEvent.click(screen.getByText('اختر الفرع...'))
    return screen.getByPlaceholderText('ابحث بالكود أو الاسم...')
  }

  it('finds a branch by code', () => {
    fireEvent.change(open(), { target: { value: 'nsr' } })
    expect(screen.getByText('Nasr City')).toBeTruthy()
    expect(screen.queryByText('Maadi')).toBeNull()
  })

  it('finds a branch by wildcard on the name', () => {
    fireEvent.change(open(), { target: { value: 'ma*di' } })
    expect(screen.getByText('Maadi')).toBeTruthy()
    expect(screen.queryByText('Nasr City')).toBeNull()
  })

  it('finds a branch by wildcard on the SOFTECH id', () => {
    fireEvent.change(open(), { target: { value: 'b*9' } })
    expect(screen.getByText('Nasr City')).toBeTruthy()
  })
})

describe('NotificationPanel', () => {
  const now = new Date().toISOString()
  const notifications = [
    { id: 1, title: 'Stock running low', body: 'Panadol', is_read: false, created_at: now },
    { id: 2, title: 'Invoice posted', body: 'Done', is_read: false, created_at: now },
  ]
  it('filters by a wildcard on the title', () => {
    render(<NotificationPanel notifications={notifications} />)
    fireEvent.change(screen.getByPlaceholderText('بحث في الإشعارات...'), { target: { value: 'stock*low' } })
    expect(screen.getByText('Stock running low')).toBeTruthy()
    expect(screen.queryByText('Invoice posted')).toBeNull()
  })
})
