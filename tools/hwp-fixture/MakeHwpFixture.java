import java.io.File;

import kr.dogfoot.hwplib.object.HWPFile;
import kr.dogfoot.hwplib.object.bodytext.ParagraphListInterface;
import kr.dogfoot.hwplib.object.bodytext.Section;
import kr.dogfoot.hwplib.object.bodytext.control.ControlTable;
import kr.dogfoot.hwplib.object.bodytext.control.ControlType;
import kr.dogfoot.hwplib.object.bodytext.control.ctrlheader.CtrlHeaderGso;
import kr.dogfoot.hwplib.object.bodytext.control.ctrlheader.gso.HeightCriterion;
import kr.dogfoot.hwplib.object.bodytext.control.ctrlheader.gso.HorzRelTo;
import kr.dogfoot.hwplib.object.bodytext.control.ctrlheader.gso.ObjectNumberSort;
import kr.dogfoot.hwplib.object.bodytext.control.ctrlheader.gso.RelativeArrange;
import kr.dogfoot.hwplib.object.bodytext.control.ctrlheader.gso.TextFlowMethod;
import kr.dogfoot.hwplib.object.bodytext.control.ctrlheader.gso.TextHorzArrange;
import kr.dogfoot.hwplib.object.bodytext.control.ctrlheader.gso.VertRelTo;
import kr.dogfoot.hwplib.object.bodytext.control.ctrlheader.gso.WidthCriterion;
import kr.dogfoot.hwplib.object.bodytext.control.ctrlheader.sectiondefine.TextDirection;
import kr.dogfoot.hwplib.object.bodytext.control.gso.textbox.LineChange;
import kr.dogfoot.hwplib.object.bodytext.control.gso.textbox.TextVerticalAlignment;
import kr.dogfoot.hwplib.object.bodytext.control.table.Cell;
import kr.dogfoot.hwplib.object.bodytext.control.table.DivideAtPageBoundary;
import kr.dogfoot.hwplib.object.bodytext.control.table.ListHeaderForCell;
import kr.dogfoot.hwplib.object.bodytext.control.table.Row;
import kr.dogfoot.hwplib.object.bodytext.control.table.Table;
import kr.dogfoot.hwplib.object.bodytext.paragraph.Paragraph;
import kr.dogfoot.hwplib.object.bodytext.paragraph.header.ParaHeader;
import kr.dogfoot.hwplib.object.bodytext.paragraph.lineseg.LineSegItem;
import kr.dogfoot.hwplib.object.bodytext.paragraph.lineseg.ParaLineSeg;
import kr.dogfoot.hwplib.reader.HWPReader;
import kr.dogfoot.hwplib.tool.TableCellMerger;
import kr.dogfoot.hwplib.tool.blankfilemaker.BlankFileMaker;
import kr.dogfoot.hwplib.writer.HWPWriter;

/**
 * ai-server 시험용 합성 HWP 5.0 파일을 만든다(학교 문서가 아닌 지어낸 내용).
 *
 * 실행: javac -cp hwplib-1.1.9.jar MakeHwpFixture.java && java -cp hwplib-1.1.9.jar:. MakeHwpFixture 출력.hwp
 * hwplib(Apache-2.0)은 이 시험 파일을 만들 때만 쓰고 서비스 코드에는 넣지 않는다.
 */
public class MakeHwpFixture {
    private static int zOrder = 0;

    public static void main(String[] args) throws Exception {
        String output = args.length > 0 ? args[0] : "table_sample.hwp";
        HWPFile hwp = BlankFileMaker.make();
        Section section = hwp.getBodyText().getSectionList().get(0);
        section.getParagraph(0).createText();
        section.getParagraph(0).getText().addString("합성 시험 문서");

        // 표 1: 표 안 제목 줄 + 세로 병합 + 짧은 가로 병합
        Paragraph p1 = newParagraph(section, "표 1 등록금");
        ControlTable t1 = addTable(p1, new String[][]{
                {"등록금 안내", null, null},
                {"구분", "학기", "금액"},
                {"수업료", "1학기", "100"},
                {null, "2학기", "200"},
                {"비고", "동결", null},
        });
        TableCellMerger.mergeCell(t1, 0, 0, 1, 3);
        TableCellMerger.mergeCell(t1, 2, 0, 2, 1);
        TableCellMerger.mergeCell(t1, 4, 1, 1, 2);

        // 표 2: 머리 두 줄(왼쪽 위 칸이 아래로 2줄 병합)
        Paragraph p2 = newParagraph(section, "표 2 학기별 금액");
        ControlTable t2 = addTable(p2, new String[][]{
                {"구분", "1학기", null, "2학기", null},
                {null, "등록금", "입학금", "등록금", "입학금"},
                {"신입생", "100", "20", "100", "0"},
        });
        TableCellMerger.mergeCell(t2, 0, 0, 2, 1);
        TableCellMerger.mergeCell(t2, 0, 1, 1, 2);
        TableCellMerger.mergeCell(t2, 0, 3, 1, 2);

        // 표 3: 칸 하나뿐인 상자
        Paragraph p3 = newParagraph(section, "");
        addTable(p3, new String[][]{{"상자 안 안내 글"}});

        // 표 4: 칸 안에 표가 든 표
        Paragraph p4 = newParagraph(section, "표 4 연락처");
        ControlTable t4 = addTable(p4, new String[][]{
                {"부서", "안내"},
                {"학사", null},
        });
        Cell host = t4.getRowList().get(1).getCellList().get(1);
        Paragraph inner = host.getParagraphList().getParagraph(0);
        addTable(inner, new String[][]{
                {"요일", "시간"},
                {"평일", "9시"},
        });

        HWPWriter.toFile(hwp, output);
        HWPFile check = HWPReader.fromFile(output);
        System.out.println("written " + output + " sections=" + check.getBodyText().getSectionList().size());
    }

    private static Paragraph newParagraph(ParagraphListInterface list, String text) throws Exception {
        Paragraph p = list.addNewParagraph();
        ParaHeader ph = p.getHeader();
        ph.setLastInList(true);
        ph.setParaShapeId(1);
        ph.setStyleId((short) 1);
        ph.setCharShapeCount(1);
        ph.setLineAlignCount(1);
        p.createText();
        if (!text.isEmpty()) {
            p.getText().addString(text);
        }
        p.createCharShape();
        p.getCharShape().addParaCharShape(0, 1);
        p.createLineSeg();
        ParaLineSeg seg = p.getLineSeg();
        LineSegItem item = seg.addNewLineSegItem();
        item.setLineHeight(1000);
        item.setTextPartHeight(1000);
        item.setDistanceBaseLineToLineVerticalPosition(850);
        item.setLineSpace(300);
        item.setSegmentWidth(14000);
        item.getTag().setFirstSegmentAtLine(true);
        item.getTag().setLastSegmentAtLine(true);
        return p;
    }

    private static ControlTable addTable(Paragraph host, String[][] texts) throws Exception {
        if (host.getText() == null) {
            host.createText();
        }
        host.getText().addExtendCharForTable();
        ControlTable table = (ControlTable) host.addNewControl(ControlType.Table);
        CtrlHeaderGso header = table.getHeader();
        header.getProperty().setLikeWord(false);
        header.getProperty().setVertRelTo(VertRelTo.Para);
        header.getProperty().setVertRelativeArrange(RelativeArrange.TopOrLeft);
        header.getProperty().setHorzRelTo(HorzRelTo.Para);
        header.getProperty().setHorzRelativeArrange(RelativeArrange.TopOrLeft);
        header.getProperty().setWidthCriterion(WidthCriterion.Absolute);
        header.getProperty().setHeightCriterion(HeightCriterion.Absolute);
        header.getProperty().setTextFlowMethod(TextFlowMethod.FitWithText);
        header.getProperty().setTextHorzArrange(TextHorzArrange.BothSides);
        header.getProperty().setObjectNumberSort(ObjectNumberSort.Table);
        header.setWidth(14000L * texts[0].length);
        header.setHeight(2000L * texts.length);
        header.setzOrder(zOrder++);

        int rows = texts.length;
        int cols = texts[0].length;
        Table record = table.getTable();
        record.getProperty().setDivideAtPageBoundary(DivideAtPageBoundary.DivideByCell);
        record.setRowCount(rows);
        record.setColumnCount(cols);
        record.setBorderFillId(1);
        for (int r = 0; r < rows; r++) {
            record.getCellCountOfRowList().add(cols);
            Row row = table.addNewRow();
            for (int c = 0; c < cols; c++) {
                Cell cell = row.addNewCell();
                ListHeaderForCell lh = cell.getListHeader();
                lh.setParaCount(1);
                lh.getProperty().setTextDirection(TextDirection.Horizontal);
                lh.getProperty().setLineChange(LineChange.Normal);
                lh.getProperty().setTextVerticalAlignment(TextVerticalAlignment.Center);
                lh.setColIndex(c);
                lh.setRowIndex(r);
                lh.setColSpan(1);
                lh.setRowSpan(1);
                lh.setWidth(14000);
                lh.setHeight(2000);
                lh.setBorderFillId(1);
                lh.setTextWidth(14000);
                lh.setFieldName("");
                String text = texts[r][c];
                newParagraph(cell.getParagraphList(), text == null ? "" : text);
            }
        }
        return table;
    }
}
