// 거절 문장만 있는 답에 백엔드가 붙이는 정해 둔 안내(ADR-0050 결정 3)
export function RefusalGuidance({ guidance }) {
  if (!guidance) return null

  return (
    <section className="source-card guidance-card" aria-label="확인 방법 안내">
      <h2>이렇게 확인해 보세요</h2>
      <ul className="guidance-list">
        {guidance.retryHint && <li>{guidance.retryHint}</li>}
        {guidance.contactLabel && (
          <li>
            담당 부서에 전화 문의: {guidance.contactLabel}
            {guidance.contactUrl && (
              <a href={guidance.contactUrl} target="_blank" rel="noopener noreferrer" className="reference-link">
                바로가기
              </a>
            )}
          </li>
        )}
      </ul>
    </section>
  )
}
