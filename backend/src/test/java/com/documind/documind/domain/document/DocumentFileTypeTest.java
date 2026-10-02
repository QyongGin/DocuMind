package com.documind.documind.domain.document;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 업로드 형식 판별(확장자 + 파일 앞부분 서명) 단위 테스트.
 */
class DocumentFileTypeTest {

    private static final byte[] OLE = {
            (byte) 0xD0, (byte) 0xCF, 0x11, (byte) 0xE0, (byte) 0xA1, (byte) 0xB1, 0x1A, (byte) 0xE1, 0x00};
    private static final byte[] ZIP = {0x50, 0x4B, 0x03, 0x04, 0x14, 0x00};

    private static byte[] ascii(String text) {
        return text.getBytes(StandardCharsets.UTF_8);
    }

    @Test
    @DisplayName("확장자는 대소문자와 상관없이 찾고, 허용하지 않는 확장자와 확장자 없는 이름은 빈 값이다")
    void fromFilename_findsAllowedExtensionsOnly() {
        assertEquals(Optional.of(DocumentFileType.HWP), DocumentFileType.fromFilename("학사 공지.HWP"));
        assertEquals(Optional.of(DocumentFileType.HWPX), DocumentFileType.fromFilename("a.b.hwpx"));
        assertEquals(Optional.of(DocumentFileType.HTM), DocumentFileType.fromFilename("page.htm"));
        assertEquals(Optional.empty(), DocumentFileType.fromFilename("image.png"));
        assertEquals(Optional.empty(), DocumentFileType.fromFilename("README"));
        assertEquals(Optional.empty(), DocumentFileType.fromFilename(null));
    }

    @Test
    @DisplayName("PDF는 앞 1024바이트 안의 %PDF- 머리를 본다")
    void pdfSignature() {
        assertTrue(DocumentFileType.PDF.matches(ascii("%PDF-1.7\n")));
        byte[] shifted = Arrays.copyOf(new byte[10], 20);
        System.arraycopy(ascii("%PDF-"), 0, shifted, 10, 5);
        assertTrue(DocumentFileType.PDF.matches(shifted));
        assertFalse(DocumentFileType.PDF.matches(ZIP));
        assertFalse(DocumentFileType.PDF.matches(new byte[0]));
    }

    @Test
    @DisplayName("HWP는 OLE 서명, DOCX·PPTX·XLSX·HWPX는 ZIP 서명이어야 한다")
    void oleAndZipSignatures() {
        assertTrue(DocumentFileType.HWP.matches(OLE));
        assertFalse(DocumentFileType.HWP.matches(ZIP));
        assertTrue(DocumentFileType.HWPX.matches(ZIP));
        assertTrue(DocumentFileType.DOCX.matches(ZIP));
        assertFalse(DocumentFileType.DOCX.matches(OLE));
        assertFalse(DocumentFileType.XLSX.matches(ascii("PK")));
    }

    @Test
    @DisplayName("HTML은 NUL 없는 글이고 BOM·공백 다음 첫 글자가 '<'여야 한다")
    void htmlSignature() {
        assertTrue(DocumentFileType.HTML.matches(ascii("<article id=\"_contentBuilder\">")));
        assertTrue(DocumentFileType.HTML.matches(ascii("﻿\n  <!DOCTYPE html><html>")));
        assertFalse(DocumentFileType.HTML.matches(ascii("그냥 글")));
        assertFalse(DocumentFileType.HTML.matches(new byte[]{'<', 'p', '>', 0x00}));
        assertFalse(DocumentFileType.HTML.matches(OLE));
        assertFalse(DocumentFileType.HTM.matches(new byte[0]));
    }

    @Test
    @DisplayName("저장하는 MIME 형식은 형식 표의 값이다")
    void mimeTypes() {
        assertEquals("application/x-hwp", DocumentFileType.HWP.getMimeType());
        assertEquals("application/hwp+zip", DocumentFileType.HWPX.getMimeType());
        assertEquals("text/html", DocumentFileType.HTM.getMimeType());
    }
}
