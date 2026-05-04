function StatusBadge({ active, children }) {
  return <span className={active ? 'status-badge status-badge--active' : 'status-badge'}>{children}</span>
}

export default StatusBadge
