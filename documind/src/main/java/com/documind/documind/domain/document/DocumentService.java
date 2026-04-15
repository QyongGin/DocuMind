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
}
