import type { CSSProperties } from 'react'

export const modelButtonBase: CSSProperties = {
  padding: '7px 16px', borderRadius: 8, border: '1px solid #d9d9d9', background: '#fff', color: '#1f2937', cursor: 'pointer', fontSize: 13, fontWeight: 500, transition: 'all 0.2s',
}

export const modelButtonActive: CSSProperties = {
  background: '#2457A6', color: '#fff', borderColor: '#2457A6', boxShadow: '0 2px 6px rgba(36, 87, 166, 0.16)',
}
