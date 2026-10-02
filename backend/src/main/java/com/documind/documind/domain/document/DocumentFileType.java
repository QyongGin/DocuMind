package com.documind.documind.domain.document;

import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Locale;
import java.util.Optional;

/**
 * 업로드를 허용하는 문서 형식이다. 확장자로 형식을 정하고, 파일 앞부분 서명(매직 바이트)이 그 형식과 맞는지 확인한다.
 *
 * <p>브라우저가 보내는 MIME 형식은 운영체제마다 달라(HWP는 대개 {@code application/octet-stream}) 믿지 않는다.
 * 저장하는 MIME 형식도 브라우저 값 대신 이 표의 값을 쓴다. 허용 목록은 AI 서버
 * {@code ALLOWED_EXTENSIONS}(ai-server/main.py)와 관리자 화면 업로드 형식과 같게 유지한다.</p>
 */
public enum DocumentFileType {

    PDF("pdf", "application/pdf", Signature.PDF),
    DOCX("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", Signature.ZIP),
    PPTX("pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation", Signature.ZIP),
    XLSX("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", Signature.ZIP),
    // HWP 5.0은 등록된 MIME 형식이 없어 널리 쓰는 값을 쓴다
    HWP("hwp", "application/x-hwp", Signature.OLE),
    // HWPX 파일 안 mimetype 항목에 적힌 값
    HWPX("hwpx", "application/hwp+zip", Signature.ZIP),
    HTML("html", "text/html", Signature.HTML),
    HTM("htm", "text/html", Signature.HTML);

    /** 서명을 확인할 때 읽는 파일 앞부분 길이(바이트). PDF 머리는 앞 1024바이트 안에 오면 된다. */
    public static final int SIGNATURE_BYTES = 1024;

    private final String extension;
    private final String mimeType;
    private final Signature signature;

    DocumentFileType(String extension, String mimeType, Signature signature) {
        this.extension = extension;
        this.mimeType = mimeType;
        this.signature = signature;
    }

    /**
     * 파일 이름의 확장자로 형식을 찾는다.
     *
     * @param filename 원본 파일 이름
     * @return 허용하는 형식이면 그 형식, 아니면 빈 값
     */
    public static Optional<DocumentFileType> fromFilename(String filename) {
        if (filename == null || !filename.contains(".")) {
            return Optional.empty();
        }
        String extension = filename.substring(filename.lastIndexOf('.') + 1).toLowerCase(Locale.ROOT);
        return Arrays.stream(values())
                .filter(type -> type.extension.equals(extension))
                .findFirst();
    }

    /**
     * 파일 앞부분이 이 형식의 서명과 맞는지 확인한다.
     *
     * @param head 파일 앞부분(최대 {@link #SIGNATURE_BYTES}바이트)
     * @return 서명이 맞으면 true
     */
    public boolean matches(byte[] head) {
        return signature.matches(head);
    }

    /**
     * DB에 저장하는 MIME 형식을 돌려준다.
     *
     * @return 형식별 MIME 문자열
     */
    public String getMimeType() {
        return mimeType;
    }

    private enum Signature {
        // PDF: "%PDF-"가 앞 1024바이트 안에 있다
        PDF {
            @Override
            boolean matches(byte[] head) {
                return indexOf(head, "%PDF-".getBytes(StandardCharsets.US_ASCII)) >= 0;
            }
        },
        // OLE 복합 문서(HWP 5.0): D0 CF 11 E0 A1 B1 1A E1
        OLE {
            @Override
            boolean matches(byte[] head) {
                return startsWith(head, new byte[]{
                        (byte) 0xD0, (byte) 0xCF, 0x11, (byte) 0xE0, (byte) 0xA1, (byte) 0xB1, 0x1A, (byte) 0xE1});
            }
        },
        // ZIP(DOCX·PPTX·XLSX·HWPX): 'PK' 03 04
        ZIP {
            @Override
            boolean matches(byte[] head) {
                return startsWith(head, new byte[]{0x50, 0x4B, 0x03, 0x04});
            }
        },
        // HTML은 서명이 없다: NUL 바이트가 없는 글이고, BOM·공백 다음 첫 글자가 '<'이면 받는다
        HTML {
            @Override
            boolean matches(byte[] head) {
                if (head.length == 0) {
                    return false;
                }
                for (byte value : head) {
                    if (value == 0) {
                        return false;
                    }
                }
                int index = startsWith(head, new byte[]{(byte) 0xEF, (byte) 0xBB, (byte) 0xBF}) ? 3 : 0;
                while (index < head.length && Character.isWhitespace(head[index])) {
                    index++;
                }
                return index < head.length && head[index] == '<';
            }
        };

        abstract boolean matches(byte[] head);

        private static boolean startsWith(byte[] head, byte[] prefix) {
            if (head.length < prefix.length) {
                return false;
            }
            for (int i = 0; i < prefix.length; i++) {
                if (head[i] != prefix[i]) {
                    return false;
                }
            }
            return true;
        }

        private static int indexOf(byte[] head, byte[] needle) {
            outer:
            for (int i = 0; i <= head.length - needle.length; i++) {
                for (int j = 0; j < needle.length; j++) {
                    if (head[i + j] != needle[j]) {
                        continue outer;
                    }
                }
                return i;
            }
            return -1;
        }
    }
}
