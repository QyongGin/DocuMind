package com.documind.documind.domain.document;

import com.documind.documind.global.infra.fastapi.FastApiDocumentProgressResponse;
import lombok.Builder;
import lombok.Getter;

/**
 * 관리자 문서 업로드 진행률 조회 응답 DTO.
 */
// @Getter: API 응답 직렬화를 위해 필드 getter를 생성한다
@Getter
// @Builder: 단계별 progress 응답 생성 코드를 명확하게 유지한다
@Builder
public class DocumentProgressResponse {

    private Long documentId;
    private int percent;
    private String stage;
    private String message;
    private String status;

    /**
     * FastAPI 진행률 응답을 관리자 화면 응답으로 변환한다.
     *
     * @param document FastAPI 처리가 진행 중인 문서
     * @param progress FastAPI 진행률 응답
     * @return 관리자 화면용 진행률 응답
     */
    public static DocumentProgressResponse from(Document document, FastApiDocumentProgressResponse progress) {
        if (document.getProcessingStatus() == DocumentProcessingStatus.READY) {
            return completed(document);
        }
        if (document.getProcessingStatus() == DocumentProcessingStatus.FAILED) {
            return failed(document);
        }
        if (progress == null) {
            return processing(document);
        }

        return DocumentProgressResponse.builder()
                .documentId(document.getId())
                .percent(clamp(progress.getPercent()))
                .stage(progress.getStage())
                .message(progress.getMessage())
                .status(progress.getStatus())
                .build();
    }

    /** 문서 처리 완료 응답을 생성한다. */
    public static DocumentProgressResponse completed(Document document) {
        return DocumentProgressResponse.builder()
                .documentId(document.getId())
                .percent(100)
                .stage("completed")
                .message("문서 처리가 완료되었습니다.")
                .status("completed")
                .build();
    }

    /** 문서 처리 실패 응답을 생성한다. */
    public static DocumentProgressResponse failed(Document document) {
        return DocumentProgressResponse.builder()
                .documentId(document.getId())
                .percent(100)
                .stage("failed")
                .message("문서 처리에 실패했습니다.")
                .status("failed")
                .build();
    }

    /** 진행률 정보가 아직 준비되지 않은 응답을 생성한다. */
    public static DocumentProgressResponse processing(Document document) {
        return DocumentProgressResponse.builder()
                .documentId(document.getId())
                .percent(0)
                .stage("processing")
                .message("문서 처리를 준비하고 있습니다.")
                .status("processing")
                .build();
    }

    private static int clamp(int percent) {
        if (percent < 0) {
            return 0;
        }
        return Math.min(percent, 100);
    }
}
