# ECG Console — Hỗ Trợ Đọc Điện Tâm Đồ (Tích Hợp AI Vision)

Ứng dụng web lâm sàng hỗ trợ phân tích điện tâm đồ (ECG) 12 chuyển đạo, tích hợp công nghệ **AI Multimodal Vision** (Google Gemini) để tự động nhận diện ảnh chụp bản ghi điện tim từ điện thoại hoặc máy quét, trích xuất thông số và đối chiếu theo **quy trình đọc hệ thống 6 bước và hệ thống tiêu chuẩn của GS.TS. Trần Đỗ Trinh & ThS. Trần Văn Đồng** (Viện Tim Mạch Học Việt Nam).

---

## 🚀 Tính năng nổi bật

1. **Nhận diện ảnh chụp ECG bằng AI Vision (Zero-Backend):**
   - Tải ảnh chụp từ máy tính hoặc **📷 chụp trực tiếp từ camera điện thoại/tablet/webcam**.
   - Bóc tách tự động các thông số in sẵn của máy (*Vent. Rate, PR, QRS, QT/QTc, Trục*) và quan sát hình thái sóng trên 12 chuyển đạo (*ST chênh, sóng T, sóng Q hoại tử, dày thất, dấu hiệu đặc biệt*).
   - Tự động điền dữ liệu (Auto-fill) vào form và hiển thị chẩn đoán phân biệt cùng phác đồ xử trí gợi ý ngay lập tức.
2. **Kính soi bản ghi ECG tương tác (Interactive Viewer):**
   - Phóng to/thu nhỏ (lên đến 600%), xoay 90°, kéo rê chuột hoặc vuốt cảm ứng để soi chi tiết từng ô ly $1\text{ mm}$ ($0.04\text{ s} / 0.1\text{ mV}$) và dải sóng.
3. **Thư viện 5 ca lâm sàng mẫu (Demo Presets):**
   - Ca 1: Nhồi máu cơ tim cấp thành dưới (STEMI DII, DIII, aVF).
   - Ca 2: Rung nhĩ đáp ứng thất nhanh (AFib with RVR).
   - Ca 3: Hội chứng tiền kích thích Wolff–Parkinson–White (WPW).
   - Ca 4: Block nhĩ thất độ III (phân ly nhĩ thất).
   - Ca 5: Tăng Kali máu nặng (sóng T cao nhọn, QRS giãn rộng, mất P).
4. **Tiện ích lâm sàng:**
   - **Tính song song QTc:** Tính cả công thức Bazett và Fridericia (chuẩn ACC/AHA).
   - **Định hướng trục nhanh:** Dựa theo chiều sóng DI và aVF.
   - **Sao chép tóm tắt bệnh án:** Copy nhanh kết luận chuẩn y khoa vào bệnh án điện tử (HIS/EMR).
   - **In ấn chuẩn A4:** Định dạng CSS riêng cho bản in sạch đẹp, chuyên nghiệp.
5. **Bảo mật tuyệt đối:**
   - Hoạt động 100% trên trình duyệt người dùng (Client-side), API Key lưu trong `localStorage`, không gửi qua bất kỳ máy chủ trung gian nào.

---

## 📂 Danh mục tài liệu trong kho lưu trữ

- `index.html`: Ứng dụng web chính hoàn chỉnh (chỉ cần mở trực tiếp bằng trình duyệt hoặc chạy qua GitHub Pages).
- `rules.md`: Toàn bộ bộ quy tắc và tiêu chuẩn đọc điện tim chuẩn hóa theo GS. Trần Đỗ Trinh và schema JSON AI Vision.
- `PM-ECG.md`: Toàn bộ lịch sử trao đổi, tiến trình thực hiện và tài liệu dự án.
- `huong-dan-doc-ecg.pdf`: Sách Hướng dẫn đọc điện tim của GS. Trần Đỗ Trinh.
- `PDF-Huong-dan-doc-dien-tim-nhathuocngocanh.pdf`: Sách Hướng dẫn đọc điện tim (Tái bản lần thứ 10) - GS. Trần Đỗ Trinh & ThS. Trần Văn Đồng.
- `Thực Hành Đọc Điện Tim.pdf`: Tuyển tập ca lâm sàng và bản ghi điện tim thực hành.

---

## 🔑 Hướng dẫn sử dụng

1. Tải toàn bộ mã nguồn hoặc clone repository:
   ```bash
   git clone https://github.com/dpthai-bvtks/ecg-auto.git
   ```
2. Nhấp đúp chuột vào file `index.html` để mở trực tiếp trên trình duyệt (Chrome, Edge, Safari, Firefox).
3. Lấy Google Gemini API Key miễn phí tại [Google AI Studio](https://aistudio.google.com/app/apikey).
4. Bấm **"⚙️ Cài đặt API AI"** trên thanh tiêu đề ứng dụng, dán mã API Key vào và bấm **"Lưu cài đặt"**.
5. Kéo thả ảnh điện tim vào khung hoặc bấm chọn ca mẫu để bắt đầu phân tích!

---
*Biên soạn: ThS.BSCK1 Nguyễn Hùng Trấn*
