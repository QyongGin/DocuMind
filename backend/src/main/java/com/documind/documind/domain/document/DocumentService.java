package com.documind.documind.domain.document;

import com.documind.documind.domain.auth.User;
import com.documind.documind.domain.auth.UserRepository;
import com.documind.documind.domain.category.Category;
import com.documind.documind.domain.category.CategoryRepository;
import com.documind.documind.global.exception.CustomException;
import com.documind.documind.global.exception.DuplicateDocumentException;
import com.documind.documind.global.exception.ErrorCode;
import com.documind.documind.global.infra.fastapi.FastApiClient;
import com.documind.documind.global.infra.fastapi.FastApiDocumentMetadata;
import com.documind.documind.global.infra.fastapi.FastApiUploadResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import java.util.stream.Collectors;

/**
 * 문서 업로드, 목록 조회, 청크 조회, 논리 삭제를 담당하는 서비스이다.
 */
@Service
@RequiredArgsConstructor
public class DocumentService {

    private final DocumentRepository documentRepository;
    private final UserRepository userRepository;
    private final CategoryRepository categoryRepository;
    private final FastApiClient fastApiClient;
    private final DocumentProcessingService documentProcessingService;

    @Value("${document.processing.async-enabled:false}")
    private boolean asyncProcessingEnabled;

    /**
     * 문서를 업로드하고 FastAPI를 통해 청킹·임베딩·ChromaDB 저장을 요청한다.
     *
     * @param file     업로드할 파일 (PDF/HWP/HWPX/DOCX/PPTX/XLSX/HTML)
     * @param username 업로드한 관리자 계정명
     * @return 업로드 결과 (document_id, 파일명, 파일 크기, 청크 수)
     * @throws CustomException 허용하지 않는 파일 형식(확장자와 파일 내용이 다른 경우 포함)이거나 사용자를 찾을 수 없는 경우
     */
    @Transactional
    public DocumentUploadResponse upload(MultipartFile file, String username) {
        return upload(file, null, username);
    }

    /**
     * 문서를 업로드하고 선택한 카테고리를 함께 저장한다.
     *
     * @param file       업로드할 파일 (PDF/HWP/HWPX/DOCX/PPTX/XLSX/HTML)
     * @param categoryId 연결할 카테고리 PK. 미분류면 null
     * @param username   업로드한 관리자 계정명
     * @return 업로드 결과 (document_id, 파일명, 파일 크기, 청크 수)
     * @throws CustomException 허용하지 않는 파일 형식(확장자와 파일 내용이 다른 경우 포함), 사용자 없음, 카테고리 없음
     */
    @Transactional
    public DocumentUploadResponse upload(MultipartFile file, Long categoryId, String username) {
        return upload(file, categoryId, DocumentSource.EMPTY, username);
    }

    /**
     * 문서를 출처 정보(대장 ID·원래 주소·게시일·학년도)와 함께 업로드한다.
     *
     * <p>같은 파일(SHA-256)이 살아 있는 문서에 있으면 막는다. 출처 정보와 카테고리는 DB에 저장하고
     * AI 서버에 넘겨 청크 메타데이터로 넣는다(#126).</p>
     *
     * @param file       업로드할 파일 (PDF/HWP/HWPX/DOCX/PPTX/XLSX/HTML)
     * @param categoryId 연결할 카테고리 PK. 미분류면 null
     * @param source     문서 대장 정보. 없으면 {@link DocumentSource#EMPTY}
     * @param username   업로드한 관리자 계정명
     * @return 업로드 결과 (document_id, 파일명, 파일 크기, 청크 수)
     * @throws CustomException 형식이 틀리거나 같은 파일이 있으면(DUPLICATE_DOCUMENT, 409) 실패
     */
    @Transactional
    public DocumentUploadResponse upload(MultipartFile file, Long categoryId, DocumentSource source, String username) {
        long processingStartNanos = System.nanoTime();

        // 파일 형식 검증: 브라우저 MIME 대신 확장자 + 파일 앞부분 서명으로 확인한다
        DocumentFileType fileType = resolveFileType(file);

        // 업로더 조회
        User uploader = userRepository.findByUsername(username)
                .orElseThrow(() -> new CustomException(ErrorCode.USER_NOT_FOUND));

        Category category = null;
        if (categoryId != null) {
            category = categoryRepository.findById(categoryId)
                    .orElseThrow(() -> new CustomException(ErrorCode.CATEGORY_NOT_FOUND));
        }

        // 같은 파일 막기: 살아 있고 실패하지 않은 문서와 파일 지문이 같으면 거절한다
        String contentSha256 = sha256Of(file);
        rejectDuplicate(contentSha256);

        // UUID 기반 서버 저장 파일명 생성 (확장자 유지)
        String originalName = file.getOriginalFilename();
        String extension = originalName != null && originalName.contains(".")
                ? originalName.substring(originalName.lastIndexOf("."))
                : "";
        String fileName = UUID.randomUUID() + extension;

        // Document를 DB에 먼저 저장해 PK(document_id)를 확보
        // FastAPI 호출 시 document_id가 필요하므로 저장 후 호출 순서를 지킨다
        Document document = Document.create(
                uploader, category, fileName, originalName,
                file.getSize(), fileType.getMimeType(), source, contentSha256
        );
        saveNewDocument(document);
        FastApiDocumentMetadata metadata = toFastApiMetadata(document);

        if (asyncProcessingEnabled) {
            Path tempFilePath = copyToTempFile(file, extension);
            processAfterCommit(tempFilePath, originalName, document.getId(), metadata, processingStartNanos);
            return DocumentUploadResponse.builder()
                    .documentId(document.getId())
                    .originalName(document.getOriginalName())
                    .fileSize(document.getFileSize())
                    .chunkCount(document.getChunkCount())
                    .processingDurationMs(document.getProcessingDurationMs())
                    .processingStatus(document.getProcessingStatus())
                    .build();
        }

        completeSynchronously(file, document, metadata, processingStartNanos);

        return DocumentUploadResponse.builder()
                .documentId(document.getId())
                .originalName(document.getOriginalName())
                .fileSize(document.getFileSize())
                .chunkCount(document.getChunkCount())
                .processingDurationMs(document.getProcessingDurationMs())
                .processingStatus(document.getProcessingStatus())
                .build();
    }

    // 확장자로 형식을 정하고, 파일 앞부분 서명이 그 형식과 맞는지 확인한다(예: .hwp인데 PDF 내용이면 거절)
    private DocumentFileType resolveFileType(MultipartFile file) {
        DocumentFileType fileType = DocumentFileType.fromFilename(file.getOriginalFilename())
                .orElseThrow(() -> new CustomException(ErrorCode.INVALID_FILE_TYPE));
        byte[] head;
        try (InputStream inputStream = file.getInputStream()) {
            head = inputStream.readNBytes(DocumentFileType.SIGNATURE_BYTES);
        } catch (IOException e) {
            throw new CustomException(ErrorCode.FILE_READ_FAILED);
        }
        if (!fileType.matches(head)) {
            throw new CustomException(ErrorCode.INVALID_FILE_TYPE);
        }
        return fileType;
    }

    // 파일 내용의 SHA-256(16진수 64자)
    private String sha256Of(MultipartFile file) {
        try (InputStream inputStream = file.getInputStream()) {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] buffer = new byte[64 * 1024];
            int read;
            while ((read = inputStream.read(buffer)) != -1) {
                digest.update(buffer, 0, read);
            }
            return HexFormat.of().formatHex(digest.digest());
        } catch (IOException e) {
            throw new CustomException(ErrorCode.FILE_READ_FAILED);
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256을 쓸 수 없는 JVM입니다.", e);
        }
    }

    private void rejectDuplicate(String contentSha256) {
        List<Document> existing = documentRepository.findLiveByContentSha256(contentSha256);
        if (!existing.isEmpty()) {
            throw new DuplicateDocumentException(existing.get(0).getId(), existing.get(0).getOriginalName());
        }
    }

    // 동시에 같은 파일을 올리면 앱 검사를 둘 다 통과할 수 있다. 그때는 DB 유일 제약(V4)이 막고, 409로 바꿔 알린다
    private void saveNewDocument(Document document) {
        try {
            documentRepository.saveAndFlush(document);
        } catch (DataIntegrityViolationException e) {
            List<Document> existing = documentRepository.findLiveByContentSha256(document.getContentSha256());
            if (existing.isEmpty()) {
                throw e;
            }
            throw new DuplicateDocumentException(existing.get(0).getId(), existing.get(0).getOriginalName());
        }
    }

    private FastApiDocumentMetadata toFastApiMetadata(Document document) {
        DocumentSource source = document.getSource();
        Category category = document.getCategory();
        return new FastApiDocumentMetadata(
                source.ledgerId(),
                source.url(),
                source.postedAt(),
                source.academicYear(),
                category != null ? category.getId() : null,
                category != null ? category.getName() : null
        );
    }

    private void completeSynchronously(
            MultipartFile file,
            Document document,
            FastApiDocumentMetadata metadata,
            long processingStartNanos
    ) {
        // FastAPI에 파일 전송 → 청킹·임베딩·ChromaDB 저장 요청
        FastApiUploadResponse fastApiResponse = fastApiClient.uploadDocument(file, document.getId(), metadata);
        long processingDurationMs = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - processingStartNanos);
        // FastAPI 처리 완료 후 청크 수와 처리 시간을 업데이트
        document.completeProcessing(fastApiResponse.getChunks(), processingDurationMs);
    }

    private Path copyToTempFile(MultipartFile file, String extension) {
        String suffix = extension == null || extension.isBlank() ? ".upload" : extension;
        try {
            Path tempFilePath = Files.createTempFile("documind-upload-", suffix);
            try (InputStream inputStream = file.getInputStream()) {
                Files.copy(inputStream, tempFilePath, StandardCopyOption.REPLACE_EXISTING);
            }
            return tempFilePath;
        } catch (IOException e) {
            throw new CustomException(ErrorCode.FILE_READ_FAILED);
        }
    }

    private void processAfterCommit(
            Path tempFilePath,
            String originalName,
            Long documentId,
            FastApiDocumentMetadata metadata,
            long processingStartNanos
    ) {
        String filename = originalName != null ? originalName : "upload";
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override
            public void afterCommit() {
                documentProcessingService.processAsync(tempFilePath, filename, documentId, metadata, processingStartNanos);
            }

            @Override
            public void afterCompletion(int status) {
                if (status != STATUS_COMMITTED) {
                    deleteTempFile(tempFilePath);
                }
            }
        });
    }

    private void deleteTempFile(Path tempFilePath) {
        try {
            Files.deleteIfExists(tempFilePath);
        } catch (IOException ignored) {
            // 트랜잭션 롤백 시 임시 파일 정리에 실패해도 사용자 응답을 덮어쓰지 않는다.
        }
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
     * 특정 문서의 ChromaDB 청크 원문을 조회한다.
     *
     * @param documentId 조회할 문서의 PK
     * @return 청크 목록 (청크 순서 오름차순)
     * @throws CustomException 문서를 찾을 수 없는 경우 DOCUMENT_NOT_FOUND
     */
    @Transactional(readOnly = true)
    public List<DocumentChunkResponse> listChunks(Long documentId) {
        documentRepository.findByIdAndIsActiveTrue(documentId)
                .orElseThrow(() -> new CustomException(ErrorCode.DOCUMENT_NOT_FOUND));

        return fastApiClient.listDocumentChunks(documentId)
                .stream()
                .map(chunk -> DocumentChunkResponse.builder()
                        .id(chunk.getId())
                        .chunkIndex(chunk.getChunkIndex())
                        .content(chunk.getContent())
                        .metadata(chunk.getMetadata())
                        .build())
                .collect(Collectors.toList());
    }

    /**
     * 진행 중인 문서 색인의 현재 progress를 조회한다.
     *
     * @param documentId 조회할 문서의 PK
     * @return 문서 처리 진행률
     * @throws CustomException 문서를 찾을 수 없는 경우 DOCUMENT_NOT_FOUND
     */
    @Transactional(readOnly = true)
    public DocumentProgressResponse progress(Long documentId) {
        Document document = documentRepository.findByIdAndIsActiveTrue(documentId)
                .orElseThrow(() -> new CustomException(ErrorCode.DOCUMENT_NOT_FOUND));

        if (document.getProcessingStatus() == null || document.getProcessingStatus() == DocumentProcessingStatus.READY) {
            return DocumentProgressResponse.completed(document);
        }
        if (document.getProcessingStatus() == DocumentProcessingStatus.FAILED) {
            return DocumentProgressResponse.failed(document);
        }

        return DocumentProgressResponse.from(document, fastApiClient.getDocumentProgress(documentId));
    }

    /**
     * 문서를 논리 삭제하고 ChromaDB에서 청크를 제거한다.
     *
     * <p>FastAPI 호출이 실패하면 {@code CustomException}(RuntimeException)이 발생해
     * {@code @Transactional}이 롤백되므로 DB도 활성 상태를 유지한다.
     * HTTP 호출을 {@code @Transactional} 외부로 이동하는 방식({@code @TransactionalEventListener})은
     * FastAPI 실패 시 DB 롤백이 불가능해 {@code is_active=false}인 문서의 청크가 RAG 검색에
     * 계속 노출되는 더 심각한 문제가 발생한다. 이 트레이드오프를 고려해 현재 구조를 유지한다.</p>
     *
     * <p>알려진 엣지 케이스: FastAPI 삭제 성공 후 DB 커밋 직전 장애가 발생하면 Chroma 청크는
     * 삭제됐으나 DB는 활성 상태로 남는 불일치가 생길 수 있다. ChromaDB는 존재하지 않는
     * ID 삭제 요청을 무시하므로, 동일 문서에 대해 삭제를 재시도하면 정상 처리된다.</p>
     *
     * <p>{@code @Transactional} 범위 내에서 HTTP 호출이 발생하므로 FastAPI 응답 지연 시
     * DB 커넥션이 그 시간만큼 점유된다. ADMIN 전용 엔드포인트로 동시 호출 빈도가 낮고,
     * FastAPI 클라이언트의 최대 대기 시간은 {@code fastapi.response-timeout} 프로퍼티로
     * 외부화돼 있으므로 무한 점유는 발생하지 않는다.</p>
     *
     * @param documentId 삭제할 문서의 PK
     * @throws CustomException 문서를 찾을 수 없는 경우 DOCUMENT_NOT_FOUND
     * @throws CustomException FastAPI 청크 삭제 실패 시 FASTAPI_DELETE_FAILED
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
