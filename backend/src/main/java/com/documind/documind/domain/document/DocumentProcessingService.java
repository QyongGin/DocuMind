package com.documind.documind.domain.document;

import com.documind.documind.global.exception.CustomException;
import com.documind.documind.global.infra.fastapi.FastApiClient;
import com.documind.documind.global.infra.fastapi.FastApiDocumentMetadata;
import com.documind.documind.global.infra.fastapi.FastApiUploadResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.io.FileSystemResource;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.concurrent.TimeUnit;

/**
 * 업로드된 문서 파일을 FastAPI로 전달하고 처리 결과를 DB에 반영한다.
 */
// @Service: 문서 색인 후속 처리를 Spring Bean으로 등록한다.
@Service
@RequiredArgsConstructor
@Slf4j
public class DocumentProcessingService {

    private final DocumentRepository documentRepository;
    private final FastApiClient fastApiClient;
    private final TransactionTemplate transactionTemplate;

    private static final String UNEXPECTED_FAILURE_MESSAGE = "AI 서버가 문서를 처리하지 못했습니다. 잠시 뒤 다시 올려 주세요.";

    /**
     * 문서 색인을 백그라운드 스레드에서 수행한다.
     *
     * @param tempFilePath         요청 종료 뒤에도 읽을 수 있게 복사해 둔 임시 파일 경로
     * @param originalFilename     FastAPI multipart filename으로 전달할 원본 파일명
     * @param documentId           MySQL documents PK
     * @param metadata             청크마다 넣을 문서 메타데이터(대장 정보·카테고리)
     * @param processingStartNanos 업로드 요청을 받은 시점의 nano time
     */
    @Async("documentProcessingExecutor")
    public void processAsync(
            Path tempFilePath,
            String originalFilename,
            Long documentId,
            FastApiDocumentMetadata metadata,
            long processingStartNanos
    ) {
        try {
            process(tempFilePath, originalFilename, documentId, metadata, processingStartNanos);
        } catch (RuntimeException ignored) {
            // 실패 상태와 상세 로그는 process()에서 이미 기록한다.
        }
    }

    private FastApiUploadResponse process(
            Path tempFilePath,
            String originalFilename,
            Long documentId,
            FastApiDocumentMetadata metadata,
            long processingStartNanos
    ) {
        try {
            FastApiUploadResponse response = fastApiClient.uploadDocument(
                    new FileSystemResource(tempFilePath),
                    originalFilename,
                    documentId,
                    metadata
            );
            long processingDurationMs = elapsedMillis(processingStartNanos);
            markReady(documentId, response.getChunks(), processingDurationMs);
            return response;
        } catch (CustomException e) {
            // ErrorCode 메시지와 AI 서버 422 이유는 화면에 보여도 되는 문장이라 그대로 남긴다
            markFailed(documentId, elapsedMillis(processingStartNanos), e.getMessage());
            log.warn("문서 색인 처리 실패. documentId={} reason={}", documentId, e.getMessage(), e);
            throw e;
        } catch (RuntimeException e) {
            // 예상하지 못한 오류의 내부 글은 화면에 내보내지 않는다
            markFailed(documentId, elapsedMillis(processingStartNanos), UNEXPECTED_FAILURE_MESSAGE);
            log.warn("문서 색인 처리 실패. documentId={}", documentId, e);
            throw e;
        } finally {
            deleteTempFile(tempFilePath, documentId);
        }
    }

    private void markReady(Long documentId, int chunkCount, long processingDurationMs) {
        transactionTemplate.executeWithoutResult(status ->
                documentRepository.findById(documentId)
                        .filter(Document::getIsActive)
                        .ifPresent(document -> document.completeProcessing(chunkCount, processingDurationMs))
        );
    }

    private void markFailed(Long documentId, long processingDurationMs, String reason) {
        transactionTemplate.executeWithoutResult(status ->
                documentRepository.findById(documentId)
                        .filter(Document::getIsActive)
                        .ifPresent(document -> document.failProcessing(processingDurationMs, reason))
        );
    }

    private long elapsedMillis(long processingStartNanos) {
        return TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - processingStartNanos);
    }

    private void deleteTempFile(Path tempFilePath, Long documentId) {
        try {
            Files.deleteIfExists(tempFilePath);
        } catch (IOException e) {
            log.warn("문서 임시 파일 삭제 실패. documentId={} path={}", documentId, tempFilePath, e);
        }
    }
}
