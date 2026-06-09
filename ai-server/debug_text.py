from langchain_opendataloader_pdf import OpenDataLoaderPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
import re

loader = OpenDataLoaderPDFLoader(
    file_path="/Users/gim-yongjin/Developer/Project/DocuMind/Assets/test_docs/01-02-01-학칙(20260130).pdf",
    format="markdown"
)
docs = loader.load()
full_text = "\n".join([doc.page_content for doc in docs])
full_text = re.sub(r'([가-힣])\n{3,}([가-힣])', r'\1\2', full_text)
full_text = re.sub(r'\n{3,}', '\n\n', full_text)

# \n\n으로 직접 split해서 어떤 조각이 생기는지 확인
raw_pieces = full_text.split('\n\n')
print("=== \\ n\\n 기준 raw 조각 (앞 8개) ===")
for i, p in enumerate(raw_pieces[:8]):
    print(f"조각 {i}: ({len(p)}글자) {repr(p[:80])}")
print()

splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,
    chunk_overlap=0,
    length_function=len
)
raw_texts = splitter.split_text(full_text)

overlapped_texts = []
for i, text in enumerate(raw_texts):
    if i == 0:
        overlapped_texts.append(text)
    else:
        overlap = raw_texts[i - 1][-50:]
        overlapped_texts.append(overlap + "\n" + text)

chunks = overlapped_texts  # 리스트 직접 사용, create_documents 재분할 방지

print(f"총 청크 수: {len(chunks)}\n")

# 청크 크기 분포
sizes = [len(c) for c in chunks]
print(f"최소: {min(sizes)}글자")
print(f"최대: {max(sizes)}글자")
print(f"평균: {sum(sizes)//len(sizes)}글자")
print(f"500글자 이상: {sum(1 for s in sizes if s >= 500)}개")
print(f"200글자 미만: {sum(1 for s in sizes if s < 200)}개")
print()

# 앞 5개 청크 내용 출력
for i, chunk in enumerate(chunks[:5]):
    print(f"=== 청크 {i+1} === ({len(chunk)}글자)")
    print(chunk)
    print()
