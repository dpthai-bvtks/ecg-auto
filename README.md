# ECG Console — Hỗ Trợ Đọc Điện Tâm Đồ (Tích Hợp AI Vision)

Ứng dụng web lâm sàng hỗ trợ phân tích điện tâm đồ (ECG) 12 chuyển đạo, tích hợp công nghệ **AI Multimodal Vision** (Google Gemini) để tự động nhận diện ảnh chụp bản ghi điện tim từ điện thoại hoặc máy quét, trích xuất thông số và đối chiếu theo **quy trình đọc hệ thống 6 bước và hệ thống tiêu chuẩn của GS.TS. Trần Đỗ Trinh & ThS. Trần Văn Đồng** (Viện Tim Mạch Học Việt Nam).

---

## 🚀 Tính năng nổi bật

1. **Nhận diện ảnh chụp ECG bằng AI Vision (Zero-Backend):**
   - Tải ảnh chụp từ máy tính hoặc **📷 chụp trực tiếp từ camera điện thoại/tablet/webcam**.
   - Bóc tách tự động các thông số in sẵn của máy (*Vent. Rate, PR, QRS, QT/QTc, Trục*) và quan sát hình thái sóng trên 12 chuyển đạo (*ST chênh, sóng T, sóng Q hoại tử, dày thất, dấu hiệu đặc biệt*).
   - Tự động điền dữ liệu (Auto-fill) vào form và hiển thị chẩn đoán phân biệt cùng phác đồ xử trí gợi ý ngay lập tức.
2. **Thiết kế Đáp ứng Đa thiết bị Toàn diện (Mobile, Tablet & Laptop/PC):**
   - **Tối ưu hóa đa màn hình:** Tự động thích ứng hoàn hảo từ màn hình điện thoại nhỏ (320px–480px), máy tính bảng (portrait/landscape 600px–1024px) đến laptop/PC màn hình lớn (>1024px).
   - **Thanh Tab di động thông minh (Sticky Segmented Control):** Trên điện thoại/máy tính bảng, ứng dụng cung cấp thanh chuyển đổi nhanh giữa `[ 📋 Nhập liệu & ECG ]` và `[ 🩺 Chẩn đoán & Xử trí ]`, tự động chuyển sang tab kết quả ngay khi phân tích xong hoặc nạp ca mẫu.
   - **Nút nổi kết quả (Floating Action Button):** Ghim góc dưới bên phải màn hình di động với đèn trạng thái nhấp nháy khi có kết quả mới.
   - **Kính soi ECG cảm ứng đa điểm (Touch Gestures):** Hỗ trợ kéo rê 1 ngón tay và phóng to/thu nhỏ 2 ngón tay (Pinch-to-zoom) mượt mà trên màn hình cảm ứng điện thoại/tablet.
   - **Nút bấm & Thẻ chọn chuẩn công thái học ngón tay:** Các ô chọn nhanh, checkbox và radio được tạo hình chip bo tròn với kích thước tối thiểu 44px dễ dàng thao tác tại giường bệnh; chống giật zoom trên iOS Safari.
3. **Tích hợp Bệnh cảnh Lâm sàng & Cận lâm sàng (Clinical Decision Support):**
   - **Thẻ chọn nhanh 12 dấu hiệu then chốt:** Đau ngực cấp <2h, đau sau xương ức lan tay trái, khó thở khi nằm, ngất đột ngột, tụt HA / sốc tim, men tim Troponin (+), Kali máu tăng/hạ, EF giảm, đang dùng Digoxin/Amiodarone.
   - **Nhập liệu sinh hiệu & xét nghiệm:** Huyết áp, mạch, SpO2, men tim (hs-cTnT/I), điện giải đồ (K+, Na+, Ca2+, Mg2+), siêu âm tim EF% và rối loạn vận động vùng, thuốc đang sử dụng.
   - **Thẻ Gợi ý Chẩn đoán & Phác đồ Xử trí Cấp cứu:** Phân tầng nguy cơ trực quan (Nguy cơ rất cao, Nguy cơ cao, Trung bình, Thấp), chẩn đoán phân biệt, checklist hành động cấp cứu ban đầu có thể tích chọn, phác đồ thuốc cụ thể theo Bộ Y tế & VNHA/ESC, cùng khung cảnh báo chống chỉ định đặc biệt.
4. **Kính soi bản ghi ECG tương tác (Interactive Viewer):**
   - Phóng to/thu nhỏ (lên đến 600%), xoay 90°, kéo rê chuột hoặc vuốt cảm ứng để soi chi tiết từng ô ly $1\text{ mm}$ ($0.04\text{ s} / 0.1\text{ mV}$) và dải sóng.
5. **Thư viện 7 ca lâm sàng mẫu (Demo Presets):**
   - Ca 1: Nhồi máu cơ tim cấp thành dưới (STEMI DII, DIII, aVF — kèm đau ngực cấp, vã mồ hôi, tụt HA, Troponin tăng).
   - Ca 2: Rung nhĩ đáp ứng thất nhanh (AFib with RVR — kèm khó thở, hồi hộp, phác đồ DOAC CHA2DS2-VASc = 3).
   - Ca 3: Hội chứng tiền kích thích Wolff–Parkinson–White (WPW — chỉ định triệt đốt RF, chống chỉ định Digoxin/chẹn AV).
   - Ca 4: Block nhĩ thất độ III (phân ly nhĩ thất — kèm ngất Adams-Stokes, tụt HA, tạo nhịp cấp cứu).
   - Ca 5: Tăng Kali máu nặng (sóng T cao nhọn hình lều, QRS giãn rộng, K+ 7.4 mmol/L — cấp cứu Canxi + Insulin/Glucose + Lọc máu).
   - Ca 6: Hội chứng Brugada Type 1 điển hình (ST vòm coved-type ở V1-V2, T âm — tiền sử ngất, chỉ định cấy ICD).
   - Ca 7: Hội chứng QT dài (LQTS — QTc kéo dài 526ms, hạ K+/Mg2+, cấp cứu Magnesium sulfate TM).
5. **Tiện ích lâm sàng & EMR:**
   - **Tính song song QTc:** Tính cả công thức Bazett và Fridericia (chuẩn ACC/AHA).
   - **Định hướng trục nhanh:** Dựa theo chiều sóng DI và aVF.
   - **Sao chép tóm tắt bệnh án:** Copy nhanh kết luận chuẩn y khoa kèm sinh hiệu và cận lâm sàng vào bệnh án điện tử (HIS/EMR).
   - **In ấn chuẩn A4:** Định dạng CSS riêng cho bản in sạch đẹp, chuyên nghiệp.
6. **Bảo mật tuyệt đối:**
   - Hoạt động 100% trên trình duyệt người dùng (Client-side), API Key lưu trong `localStorage`, không gửi qua bất kỳ máy chủ trung gian nào.

---

## 📂 Danh mục tài liệu trong kho lưu trữ

- `index.html`: Ứng dụng web chính hoàn chỉnh (chạy trực tiếp trên trình duyệt hoặc qua GitHub Pages).
- `rules.md`: Toàn bộ bộ quy tắc 7 phần và tiêu chuẩn đọc điện tim + phác đồ cấp cứu chuẩn hóa theo GS. Trần Đỗ Trinh, Bộ môn Tim mạch ĐH Y Hà Nội & Viện Tim mạch VN (PGS.TS. Phạm Mạnh Hùng, TS. Phan Đình Phong).
- `PM-ECG.md`: Toàn bộ lịch sử trao đổi, tiến trình thực hiện và tài liệu dự án.
- `tai-lieu-tham-khao/`: Thư mục lưu trữ toàn bộ sách giáo trình, bài giảng và ngân hàng ca bệnh điện tâm đồ tham khảo:
  - `4.-Bai-giang-dien-tam-do.pdf`: Sách Bài giảng Điện tâm đồ - PGS.TS.BS. Phạm Mạnh Hùng & TS.BSNT. Phan Đình Phong.
  - `Đọc điện tâm đồ dễ hơn.pdf`: Chuyên khảo 147 trang với 220 chuyên mục kỹ thuật đo, lỗi đảo cực và bệnh lý tim mạch.
  - `bai-giang-dien-tam-do-vieclamvui.pdf` / `.pptx`: Bài giảng Điện tâm đồ bình thường & bệnh lý - ThS.BS. Nguyễn Anh Tuấn & ThS.BS. Phan Đình Phong.
  - `huong-dan-doc-ecg.pdf`: Sách Hướng dẫn đọc điện tim của GS. Trần Đỗ Trinh.
  - `PDF-Huong-dan-doc-dien-tim-nhathuocngocanh.pdf`: Sách Hướng dẫn đọc điện tim (Tái bản lần 10) - GS. Trần Đỗ Trinh & ThS. Trần Văn Đồng.
  - `Thực Hành Đọc Điện Tim.pdf`: Tuyển tập ca lâm sàng và bản ghi điện tim thực hành.
  - `CLS ECG.pdf`, `Sổ tay điện tâm đồ.pdf`, `Điện Tâm Đồ Trong Thực Hành Lâm Sàng.pdf`: Ngân hàng ca bệnh thực hành lâm sàng.

---

## 🔑 Hướng dẫn sử dụng

1. Tải toàn bộ mã nguồn hoặc clone repository:
   ```bash
   git clone https://github.com/dpthai-bvtks/ecg-auto.git
   ```
2. Nhấp đúp chuột vào file `index.html` để mở trực tiếp trên trình duyệt (Chrome, Edge, Safari, Firefox) hoặc truy cập trực tiếp qua GitHub Pages.
3. Kéo thả ảnh điện tim vào khung hoặc chọn một ca mẫu thử nghiệm (Preset).
4. Nhập thêm triệu chứng lâm sàng và cận lâm sàng (hoặc bấm chọn các thẻ nhanh) để nhận gợi ý chẩn đoán và phác đồ xử trí cấp cứu toàn diện!
5. Bấm **"📋 Sao chép tóm tắt"** để dán vào hồ sơ bệnh án hoặc **"🖨️ In phiếu kết quả"** để in bản ghi A4.
