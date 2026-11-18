import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import SearchTierChip from './SearchTierChip'

describe('SearchTierChip', () => {
  afterEach(cleanup)

  it.each([
    [{ learned: true }, 'من الذاكرة'],
    [{ ingredient: true, ingredient_name: 'DICLOFENAC' }, 'مادة فعالة: DICLOFENAC'],
    [{ sound: true }, 'بالنطق'],
    [{ approx: true }, 'تقريبي'],
    [{ code_part: true }, 'جزء من الكود'],
    [{ code_prefix: true }, 'بداية الكود'],
  ])('renders the label for %j', (row, label) => {
    render(<SearchTierChip row={row} />)
    expect(screen.getByText(label)).toBeTruthy()
  })

  it('renders nothing for an exact row', () => {
    const { container } = render(<SearchTierChip row={{}} />)
    expect(container.firstChild).toBeNull()
  })

  it('gives synonym no chip', () => {
    const { container } = render(<SearchTierChip row={{ synonym: true }} />)
    expect(container.firstChild).toBeNull()
  })

  it('ranks code_prefix just before code_part, below approx', () => {
    render(<SearchTierChip row={{ code_prefix: true, code_part: true }} />)
    expect(screen.getByText('بداية الكود')).toBeTruthy()
    expect(screen.queryByText('جزء من الكود')).toBeNull()
    cleanup()
    render(<SearchTierChip row={{ approx: true, code_prefix: true }} />)
    expect(screen.getByText('تقريبي')).toBeTruthy()
  })

  it('shows only the highest-priority chip', () => {
    const { container } = render(<SearchTierChip row={{ learned: true, sound: true }} />)
    expect(screen.getByText('من الذاكرة')).toBeTruthy()
    expect(screen.queryByText('بالنطق')).toBeNull()
    expect(container.querySelectorAll('span').length).toBe(1)
  })
})
