package com.documind.documind.domain.document;

import com.documind.documind.domain.auth.User;
import com.documind.documind.domain.auth.UserRepository;
import com.documind.documind.global.exception.CustomException;
import com.documind.documind.global.exception.ErrorCode;
import com.documind.documind.global.infra.fastapi.FastApiClient;
import com.documind.documind.global.infra.fastapi.FastApiUploadResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

import java.util.Arrays;
import java.util.List;
import java.util.UUID;
import java.util.stream.Collectors;

// 문서 업로드 비즈니스 로직을 담당
@Service
@RequiredArgsConstructor
public class DocumentService {

    private final DocumentRepository documentRepository;
    private final UserRepository userRepository;
    private final FastApiClient fastApiClient;

    // 허용 MIME 타입 목록. FastAPI 파서가 지원하는 형식과 동기화
    private static final List<String> ALLOWED_MIME_TYPES = Arrays.asList(
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document", // DOCX
            "application/vnd.openxmlformats-officedocument.presentationml.presentation", // PPTX
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" // XLSX
    );

    /**
     * 문서를 업로드하고 FastAPI를 통해 청킹·임베딩·ChromaDB 저장을 요청한다.
     *
     * @param file     업로드할 파일 (PDF/DOCX/PPTX/XLSX)
     * @param username 업로드한 관리자 계정명
     * @return 업로드 결과 (document_id, 파일명, 파일 크기, 청크 수)
     * @throws CustomException 허용하지 않는 파일 형식이거나 사용자를 찾을 수 없는 경우
     */
    @Transactional
    public DocumentUploadResponse upload(MultipartFile file, String username) {
        // 파일 형식 검증
        String mimeType = file.getContentType();
        if (mimeType == null || !ALLOWED_MIME_TYPES.contains(mimeType)) {
            throw new CustomException(ErrorCode.INVALID_FILE_TYPE);
        }

        // 업로더 조회
        User uploader = userRepository.findByUsername(username)
                .orElseThrow(() -> new CustomException(ErrorCode.USER_NOT_FOUND));

        // UUID 기반 서버 저장 파일명 생성 (확장자 유지)
        String originalName = file.getOriginalFilename();
        String extension = originalName != null && originalName.contains(".")
                ? originalName.substring(originalName.lastIndexOf("."))
                : "";
        String fileName = UUID.randomUUID() + extension;

        // Document를 DB에 먼저 저장해 PK(document_id)를 확보
        // FastAPI 호출 시 document_id가 필요하므로 저장 후 호출 순서를 지킨다
        Document document = Document.create(
                uploader, null, fileName, originalName,
                file.getSize(), mimeType
        );
        documentRepository.save(document);

        // FastAPI에 파일 전송 → 청킹·임베딩·ChromaDB 저장 요청
        FastApiUploadResponse fastApiResponse = fastApiClient.uploadDocument(file, document.getId());

        // FastAPI 처리 완료 후 청크 수 업데이트
        document.updateChunkCount(fastApiResponse.getChunks());

        return DocumentUploadResponse.builder()
                .documentId(document.getId())
                .originalName(document.getOriginalName())
                .fileSize(document.getFileSize())
                .chunkCount(document.getChunkCount())
                .build();
    }

    /**
     * 활성화된 문서 전체를 최신순으로 조회한다.
     *
     * @return is_active=true인 문서 목록 (최신순)
     */
    @Transactional(readOnly = true)
    public List<DocumentListResponse> list() {
        return documentRepository.findAllByIsActiveTrueOrderByCreatedAtDesc()
                .stream()
                .map(DocumentListResponse::from)
                .collect(Collectors.toList());
    }

    /**
     * 문서를 논리 삭제하고 ChromaDB에서 청크를 제거한다.
     *
     * <p>DB 논리 삭제(is_active=false)와 ChromaDB 청크 삭제를 하나의 트랜잭션으로 처리한다.
     * FastAPI 호출이 실패하면 {@code CustomException}(RuntimeException)이 발생해
     * {@code @Transactional}이 롤백되므로 DB도 활성 상태로 유지된다.
     * 단, FastAPI 호출이 성공한 뒤 트랜잭션 커밋 직전 장애가 발생하면 ChromaDB에서는
     * 청크가 삭제됐으나 DB는 활성 상태로 남는 불일치가 생길 수 있다.
     * 이 경우 다음 삭제 요청 시 FastAPI가 이미 없는 청크 삭제를 시도하지만 ChromaDB는
     * 존재하지 않는 ID 삭제를 무시하므로 재시도하면 정상 처리된다.</p>
     *
     * @param documentId 삭제할 문서의 PK
     * @throws CustomException 문서를 찾을 수 없는 경우 DOCUMENT_NOT_FOUND
     */
    @Transactional
    public void delete(Long documentId) {
        Document document = documentRepository.findByIdAndIsActiveTrue(documentId)
                .orElseThrow(() -> new CustomException(ErrorCode.DOCUMENT_NOT_FOUND));

        document.deactivate();
        // FastAPI 호출 실패 시 @Transactional 롤백으로 document.deactivate()도 되돌아간다
        fastApiClient.deleteDocument(documentId);
    }
}
