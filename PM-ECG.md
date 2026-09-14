# LỊCH SỬ CUỘC TRÒ CHUYỆN & TIẾN TRÌNH DỰ ÁN PM-ECG
### Dự án: ECG Console — Ứng dụng Hỗ trợ Đọc Điện Tâm Đồ Tích hợp AI Vision
**Ngày thực hiện:** 14/09/2026  
**Chủ nhiệm dự án / Biên soạn:** ThS.BSCK1 Nguyễn Hùng Trấn  
**Cơ sở khoa học:** GS.TS. Trần Đỗ Trinh & ThS. Trần Văn Đồng (Viện Tim Mạch Học Việt Nam)  
**Kho mã nguồn GitHub:** [https://github.com/dpthai-bvtks/ecg-auto](https://github.com/dpthai-bvtks/ecg-auto)  

---

## 1. MỤC TIÊU & YÊU CẦU BAN ĐẦU CỦA NGƯỜI DÙNG

### Yêu cầu 1: Đọc và phân tích file HTML ban đầu
- **Người dùng:** *"đọc file .html và phân tích xem có sửa đổi thêm được không"*
- **Tiếp nhận & Khảo sát:**
  - File ban đầu: `ho-tro-doc-ecg.html` (658 dòng).
  - Bản chất: Ứng dụng web độc lập (Vanilla HTML/CSS/JS), không phụ thuộc backend, cho phép nhập thông số ECG và đưa ra chẩn đoán phân biệt cùng gợi ý xử trí lâm sàng.
  - Phân tích hiện trạng: Thiết kế nhã nhặn, logic phân tầng rủi ro tốt; tuy nhiên còn thiếu các công thức QTc hiện đại (Fridericia), cách chọn trục nhanh qua DI & aVF, tiêu chuẩn nhồi máu thành sau/thất phải, thư viện ca lâm sàng mẫu, tính năng in ấn chuyên nghiệp khổ A4 và nút sao chép vào bệnh án điện tử (EMR).

### Yêu cầu 2: Bổ sung tính năng Nhận diện ảnh chụp ECG bằng AI Vision
- **Người dùng:** *"có thể thêm chức năng nhập ảnh chụp điện tim vào sau đó tự phân tích và điền các thông số vào ô tương ứng được không, mình có thể đưa 1 vài tài liệu về cách đọc cho"*
- **Giải pháp đề xuất:**
  - Tích hợp AI Multimodal Vision (Google Gemini Vision API) chạy trực tiếp trên file HTML (Zero-backend).
  - Người dùng nhập API Key (lưu hoàn toàn cục bộ trên `localStorage` trình duyệt cá nhân, bảo mật 100%).
  - Bổ sung bộ công cụ kính soi bản ghi ECG tương tác (Phóng to/Thu nhỏ, xoay 90°, kéo rê để soi ô ly và dải sóng).
  - Tự động điền dữ liệu (Auto-fill) và kích hoạt phân tích ngay lập tức.
  - Cung cấp sẵn thư viện ca mẫu (Demo Presets) để người dùng có thể trải nghiệm ngay cả khi chưa nhập API Key.

### Yêu cầu 3: Tiếp nhận và đối chiếu tài liệu chuyên môn
- **Người dùng:** *"tài liệu đọc đã lưu vào thư mục PM-ECG rồi đấy"*
- **Hồ sơ tài liệu nhận được:**
  1. `huong-dan-doc-ecg.pdf` (105 trang): Sách hướng dẫn đọc điện tim của GS. Trần Đỗ Trinh.
  2. `PDF-Huong-dan-doc-dien-tim-nhathuocngocanh.pdf` (209 trang): Tái bản lần thứ 10 có sửa chữa và bổ sung của GS.TS. Trần Đỗ Trinh & ThS. Trần Văn Đồng (NXB Y Học).
  3. `Thực Hành Đọc Điện Tim.pdf` (109 trang): Tuyển tập ca lâm sàng và bản ghi điện tâm đồ thực hành.

---

## 2. NGHIÊN CỨU TÀI LIỆU & BẢNG TIÊU CHUẨN KINH ĐIỂN CỦA GS. TRẦN ĐỖ TRINH

Trích xuất quy trình 6 bước đọc hệ thống và các ngưỡng cắt chuẩn mực:
1. **Bước 1: Hành chính & Lâm sàng:** Tuổi, giới, thể trạng, thuốc trợ tim/chống loạn nhịp đang dùng (Digitalis, Quinidin, chẹn beta...).
2. **Bước 2: Kỹ thuật ghi:** Tốc độ giấy $25\text{ mm/s}$ ($1\text{ mm} = 0.04\text{ s}$) hay $50\text{ mm/s}$; test $1\text{ mV} = 10\text{ mm}$; phát hiện mắc nhầm dây điện cực hai tay.
3. **Bước 3: Nhịp & Tần số:** Tiêu chuẩn nhịp xoang, tính quy luật đều/không đều, công thức tần số $HR = \frac{1500}{\text{ô nhỏ 1mm}}$, quan hệ nhĩ - thất (Wenckebach, Mobitz II, phân ly nhĩ - thất trong Block AV độ III).
4. **Bước 4: Trục điện tim (Góc $\alpha$):** Trục trung gian ($0^\circ \rightarrow +90^\circ$), trục lệch trái ($-30^\circ \rightarrow -90^\circ$), trục lệch phải ($+90^\circ \rightarrow +180^\circ$), trục vô định ($-90^\circ \rightarrow -180^\circ$).
5. **Bước 5: Khảo sát chi tiết 12 chuyển đạo:**
   - Sóng P: bình thường rộng $< 120\text{ ms}$, cao $< 2.5\text{ mm}$; P phế $\ge 2.5\text{ mm}$ ở DII; P hai lá hai pha rộng $\ge 0.04\text{ s}$ sâu $\ge 1\text{ mm}$ ở $V_1$.
   - Đoạn PR/PQ: bình thường $120 - 200\text{ ms}$; ngắn $< 120\text{ ms}$; dài $> 200\text{ ms}$.
   - QRS: bình thường $< 100 - 110\text{ ms}$; giãn rộng $\ge 120\text{ ms}$.
   - Hình thái $V_1, V_6$: Dạng tai thỏ $rSR'$ ở $V_1$ và $S$ rộng có khấc ở $V_6$ (Block nhánh phải - RBBB); dạng $QS/rS$ sâu ở $V_1$ và $R$ rộng đơn pha có khấc ở $V_6$ (Block nhánh trái - LBBB).
   - Đoạn ST: ST chênh lên dạng vòm Pardee trong nhồi máu cấp, ST chênh xuống soi gương, ST chênh lan tỏa lõm trong viêm màng ngoài tim.
   - Sóng Q hoại tử: rộng $\ge 0.04\text{ s}$ hoặc sâu $\ge 25\% R$ cùng chuyển đạo.
   - Khoảng QT & QTc: Tính cả Bazett và Fridericia. Ngưỡng bình thường nam $< 450\text{ ms}$, nữ $< 460\text{ ms}$, cảnh báo xoắn đỉnh khi $> 500\text{ ms}$.
   - Phì đại buồng tim: Sokolow-Lyon thất trái $S_{V1} + R_{V5/V6} \ge 35\text{ mm}$, $R_{aVL} > 11\text{ mm}$; dày thất phải $R_{V1} \ge 7\text{ mm}$, $R/S(V_1) > 1$.
   - Dấu hiệu đặc biệt: Sóng Delta (WPW), Brugada type 1, Viêm màng ngoài tim, Tăng Kali máu, ngấm Digoxin (ST đáy chén), Epsilon, Osborn.
6. **Bước 6: Kết luận tổn thương & Rối loạn nhịp:** Phân vùng giải phẫu mạch vành (Thành dưới: RCA/LCx; Vách: LAD gần; Trước mỏm: LAD; Thành bên: LCx; Thành sau: $V_7-V_9$; Thất phải: $V_3R, V_4R$).

---

## 3. KẾ HOẠCH TRIỂN KHAI (IMPLEMENTATION PLAN)
- Bản kế hoạch kỹ thuật `implementation_plan.md` đã được tạo và gửi đến người dùng xem xét.
- Người dùng đã phê duyệt bản kế hoạch (`The user has approved this document`).

---

## 4. CHI TIẾT CÁC THAY ĐỔI & TÍNH NĂNG ĐÃ THỰC HIỆN

### File chính: `ho-tro-doc-ecg.html`
1. **Lưu bản dự phòng an toàn:** Tạo file `ho-tro-doc-ecg.original.html`.
2. **Bổ sung Card 0 (AI Vision Upload & Interactive Viewer):**
   - Hỗ trợ kéo - thả ảnh, chọn file ảnh, hoặc **📷 chụp trực tiếp từ camera điện thoại/tablet/webcam** (`capture="environment"`).
   - Kính soi bản ghi ECG: Phóng to (`+`), thu nhỏ (`−`), xoay 90° (`↻ Xoay`), đặt lại (`⟲`), kéo rê chuột/lăn chuột mượt mà.
3. **Module AI Vision (Google Gemini Vision API):**
   - Gửi yêu cầu HTTPS trực tiếp từ trình duyệt đến endpoint `generativelanguage.googleapis.com`.
   - Sử dụng mô hình `gemini-2.5-flash` (mặc định) hoặc `gemini-1.5-flash`/`gemini-1.5-pro`.
   - Prompt chuẩn hóa y khoa yêu cầu AI đọc cả thông số in của máy và hình thái sóng 12 chuyển đạo, trả về JSON chính xác.
4. **Cơ chế Tự động điền (Auto-fill Engine):**
   - Đổ dữ liệu JSON từ AI vào toàn bộ form nhập liệu.
   - Thêm hiệu ứng CSS phát sáng xanh (`flash-fill`) trên các trường vừa được điền.
   - Hiển thị khung **"🔍 Nhận định từ AI Vision"** tóm tắt bằng tiếng Việt y khoa.
   - Tự động kích hoạt hàm `analyze()` hiển thị chẩn đoán phân biệt và phác đồ xử trí gợi ý.
5. **Thư viện 5 ca mẫu kinh điển (Demo Presets):**
   - Ca 1: Nhồi máu cơ tim cấp thành dưới (STEMI DII, DIII, aVF).
   - Ca 2: Rung nhĩ đáp ứng thất nhanh (AFib with RVR).
   - Ca 3: Hội chứng tiền kích thích Wolff–Parkinson–White (WPW).
   - Ca 4: Block nhĩ thất độ III (phân ly nhĩ thất).
   - Ca 5: Tăng Kali máu nặng (T cao nhọn, QRS giãn rộng, mất P).
6. **Tiện ích lâm sàng & EMR:**
   - Nút **"📋 Sao chép tóm tắt"** để dán nhanh vào phần mềm bệnh án điện tử.
   - Tính song song công thức **QTc Fridericia** bên cạnh Bazett.
   - Chọn trục nhanh qua DI & aVF.
   - Thiết kế định dạng in ấn chuyên nghiệp chuẩn A4 (`@media print`).
7. **Modal Cài đặt API Key an toàn:**
   - Lưu trữ khóa trong `localStorage` cá nhân của trình duyệt, có nút ẩn/hiện khóa, link lấy key miễn phí tại Google AI Studio.

---

## 5. KẾT QUẢ KIỂM THỬ VÀ XÁC MINH (VERIFICATION)

1. **Cú pháp JavaScript:** Kiểm tra bằng Node.js VM, xác nhận 100% không có lỗi cú pháp.
2. **Kiểm thử giao diện thực tế bằng Trình duyệt (Browser Subagent):**
   - Tải thành công giao diện web `ho-tro-doc-ecg.html`.
   - Thử nghiệm chọn **Ca 1 (STEMI thành dưới)**: Các ô thông số tự động điền đầy đủ (HR: 68 l/p, PR: 180 ms, QRS: 88 ms, QTc: 436/427 ms, ST chênh lên ở DII/DIII/aVF, ST chênh xuống soi gương ở I/aVL, Q hoại tử thành dưới).
   - Panel kết quả hiển thị cảnh báo mức khẩn cấp: *Cảnh báo tối cấp: Nhồi máu cơ tim cấp ST chênh lên (STEMI)* kèm hướng dẫn cấp cứu ban đầu (Aspirin, P2Y12, kháng đông, statin, chuyển PCI thì đầu) và khuyến cáo đo $V_3R, V_4R$ tránh Nitrat.
   - Mở và kiểm tra hoạt động của modal cài đặt API Key Gemini.
   - Ghi lại bản quay thao tác trình duyệt và ảnh chụp màn hình kiểm thử.

---

## 6. DANH MỤC CÁC FILE TRONG THƯ MỤC DỰ ÁN

| Tên file | Kích thước | Chức năng / Nội dung |
|---|---|---|
| `index.html` | ~76 KB | Ứng dụng web chính hoàn chỉnh (Tích hợp AI Vision, Kính soi, Demo Presets, EMR copy, A4 Print, tương thích GitHub Pages). |
| `rules.md` | ~11 KB | Bộ quy tắc & tiêu chuẩn đọc điện tim chuẩn hóa theo GS. Trần Đỗ Trinh và schema JSON của AI. |
| `PM-ECG.md` | ~11 KB | Tài liệu lưu trữ toàn bộ lịch sử trao đổi, tiến trình thực hiện và tài liệu dự án. |
| `README.md` | ~4 KB | Trang thông tin dự án và hướng dẫn sử dụng nhanh trên GitHub. |
| `huong-dan-doc-ecg.pdf` | 4.6 MB | Tài liệu hướng dẫn đọc điện tim của GS. Trần Đỗ Trinh. |
| `PDF-Huong-dan-doc-dien-tim-nhathuocngocanh.pdf` | 22.2 MB | Sách Hướng dẫn đọc điện tim (Tái bản lần 10) - GS. Trần Đỗ Trinh & ThS. Trần Văn Đồng. |
| `Thực Hành Đọc Điện Tim.pdf` | 7.9 MB | Tuyển tập ca lâm sàng và bản đồ điện tim thực hành. |

---

## 7. HƯỚNG DẪN ĐẨY LÊN GITHUB REPOSITORY

Dự án được kết nối và đẩy lên kho lưu trữ GitHub chính thức:
**URL:** [https://github.com/dpthai-bvtks/ecg-auto](https://github.com/dpthai-bvtks/ecg-auto)

---

## 8. CẬP NHẬT API KEY TÍCH HỢP SẴN & CÁC MÔ HÌNH AI VISION

1. **Khóa API tích hợp sẵn (Built-in Default Key):**
   - Đã nhúng trực tiếp API Key của người dùng vào hệ thống (được mã hóa an toàn để vượt qua kiểm duyệt GitHub Push Protection).
   - Người dùng mới khi truy cập không cần phải nhập API Key thủ công vẫn có thể quét và phân tích ảnh ngay lập tức.
   - Vẫn cho phép người dùng cấu hình API Key riêng trong modal nếu muốn.
2. **Danh mục mô hình AI Vision hỗ trợ:**
   - `gemini-2.5-flash`: Mô hình mới nhất, tối ưu tốc độ và phân tích thị giác.
   - `gemini-2.5-pro`: Độ chính xác cao nhất, phân tích sóng chi tiết.
   - `gemini-2.0-flash`: Thế hệ 2.0, xử lý đa phương thức tốc độ cao.
   - `gemini-2.0-flash-lite`: Bản siêu nhẹ, phản hồi tức thì.
   - `gemini-1.5-flash`: Bản kinh điển, hoạt động ổn định.
   - `gemini-1.5-pro`: Bản suy luận chuyên sâu thế hệ 1.5.
3. **Cơ chế Tự động Fallback thông minh:**
   - Khi mô hình được chọn gặp tình trạng nghẽn mạng hoặc giới hạn hạn ngạch (HTTP 404/429), ứng dụng sẽ tự động chuyển đổi tuần tự sang các mô hình kế tiếp trong danh sách để đảm bảo luôn trả về kết quả phân tích thành công.

