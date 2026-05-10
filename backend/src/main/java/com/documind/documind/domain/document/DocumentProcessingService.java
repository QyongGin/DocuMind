package com.documind.documind.domain.document;

import com.documind.documind.global.infra.fastapi.FastApiClient;
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

    /**
     * 문서 색인을 백그라운드 스레드에서 수행한다.
     *
     * @param tempFilePath         요청 종료 뒤에도 읽을 수 있게 복사해 둔 임시 파일 경로
     * @param originalFilename     FastAPI multipart filename으로 전달할 원본 파일명
     * @param documentId           MySQL documents PK
     * @param processingStartNanos 업로드 요청을 받은 시점의 nano time
     */
    @Async("documentProcessingExecutor")
    public void processAsync(Path tempFilePath, String originalFilename, Long documentId, long processingStartNanos) {
        try {
            process(tempFilePath, originalFilename, documentId, processingStartNanos);
        } catch (RuntimeException ignored) {
            // 실패 상태와 상세 로그는 process()에서 이미 기록한다.
        }
    }

    private FastApiUploadResponse process(
            Path tempFilePath,
            String originalFilename,
            Long documentId,
            long processingStartNanos
    ) {
        try {
            FastApiUploadResponse response = fastApiClient.uploadDocument(
                    new FileSystemResource(tempFilePath),
                    originalFilename,
                    documentId
            );
            long processingDurationMs = elapsedMillis(processingStartNanos);
            markReady(documentId, response.getChunks(), processingDurationMs);
            return response;
        } catch (RuntimeException e) {
            long processingDurationMs = elapsedMillis(processingStartNanos);
            markFailed(documentId, processingDurationMs);
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

    private void markFailed(Long documentId, long processingDurationMs) {
        transactionTemplate.executeWithoutResult(status ->
                documentRepository.findById(documentId)
                        .filter(Document::getIsActive)
                        .ifPresent(document -> document.failProcessing(processingDurationMs))
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
