import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import BranchSelect from './BranchSelect'

const branches = [
  { id: 1, softech_branch_id: '201', name: 'Live', name_ar: 'فرع حي', kind: 'retail' },
  { id: 2, softech_branch_id: '203', name: 'Old', name_ar: 'فرع قديم', kind: 'closed' },
]

function open(props) {
  render(<BranchSelect branches={branches} onChange={vi.fn()} {...props} />)
  fireEvent.click(screen.getByText('اختر الفرع...'))
}

describe('BranchSelect closed branches', () => {
  afterEach(cleanup)

  it('hides closed branches by default', () => {
    open({})
    expect(screen.getByText('فرع حي')).toBeTruthy()
    expect(screen.queryByText('فرع قديم')).toBeNull()
  })

  it('shows closed branches with a «مغلق» tag when showClosed', () => {
    open({ showClosed: true })
    expect(screen.getByText('فرع قديم')).toBeTruthy()
    expect(screen.getByText('مغلق')).toBeTruthy()
  })
})
