// 답이 쓴 근거로 백엔드가 만든 '참고한 문서'(ADR-0050, docs/project/챗봇-답변-형식.md §1·§3)
function referencePlace(reference) {
  return [reference.site, reference.board].filter(Boolean).join(' › ')
}

export function ReferenceList({ references }) {
  if (!references?.length) return null

  return (
    <section className="source-card reference-card" aria-label="참고한 문서">
      <h2>참고한 문서</h2>
      <ul className="reference-list">
        {references.map((reference) => (
          <li key={`${reference.title}-${reference.url ?? ''}`} className="reference-item">
            {referencePlace(reference) && <p className="reference-place">{referencePlace(reference)}</p>}
            <p className="reference-title">
              <span>{reference.title}</span>
              {reference.url && (
                <a href={reference.url} target="_blank" rel="noopener noreferrer" className="reference-link">
                  원문 보기
                </a>
              )}
            </p>
            {reference.attachmentNames?.length > 0 && (
              <p className="reference-meta">첨부 {reference.attachmentNames.join(', ')}</p>
            )}
            {reference.postedAt && <p className="reference-meta">게시 {reference.postedAt}</p>}
          </li>
        ))}
      </ul>
    </section>
  )
}
